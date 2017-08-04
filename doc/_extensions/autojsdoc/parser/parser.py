# -*- coding: utf-8 -*-
import collections
import pprint

from attr import attrs, Factory, attr, astuple

from . import jsdoc
from . import utils
from .visitor import Visitor, SKIP

DECLARATOR_INIT_TO_REF = ('Literal', 'Identifier', 'MemberExpression')


class ModuleMatcher(Visitor):
    """Looks for structures of the form::

        odoo.define($string, function ($name) {

    These are *Odoo module definitions*, upon encountering one the
    matcher:

    * creates a module entry, optionally associated with the module comment
    * spawns off a :class:`ModuleBodyMatcher` on the function's body with the
      module name and the $name as "require" function
    """
    def __init__(self):
        super(ModuleMatcher, self).__init__()
        self.result = []
    def enter_Program(self, node):
        pass # allows visiting toplevel
    def enter_ExpressionStatement(self, node):
        # we're interested in expression statements (toplevel call)
        if utils.match(node, {'expression': {
            'callee': {
                'object': {'name': 'odoo'},
                'property': {'name': 'define'},
            },
        }}):
            [module, func] = node['expression']['arguments']
            mod = jsdoc.parse_comments(node.get('comments'), jsdoc.ModuleDoc)
            # set module name
            mod.parsed['module'] = module['value']
            self.result.append(mod)

            # get name of require parameter
            require = None # a module can have no dependencies
            if func['params']:
                require = func['params'][0]['name']
            mod.parsed['dependency'], mod.parsed['exports'], post = ModuleExtractor(require).visit(func['body'])
            mod._post_process.extend(post)
        # don't recurse since we've fired off a sub-visitor for the
        # bits we're interested in
        return SKIP
    def enter_generic(self, node):
        # skip all other toplevel statements
        return SKIP

ref = collections.namedtuple('Ref', 'object property')
def _name(r):
    bits = []
    while isinstance(r, ref):
        bits.append(r.property)
        r = r.object
    return '.'.join(reversed(bits))
def deref(item, prop=None):
    assert isinstance(item, ref)

    while isinstance(item, ref):
        obj = item.object
        if isinstance(obj, ref):
            obj = deref(obj)

        if isinstance(obj, (jsdoc.NSDoc, jsdoc.Unknown)):
            item = obj.get_property(item.property)
        elif isinstance(obj, jsdoc.ClassDoc):
            item = obj.get_method(item.property)
        elif isinstance(obj, dict):
            item = obj[item.property]
        elif isinstance(obj, jsdoc.PropertyDoc):
            # f'n dynamic crap
            item = jsdoc.Unknown(obj.to_dict()).get_property(item.property)
        else:
            raise ValueError("%r (%s) should be a dict or namespace" % (obj, type(obj)))
    return item

def m2r(me, scope):
    # create a ref to the scope in case it's a hoisted function declaration,
    # this may false-positive on other hoisting but w/e
    if me['type'] == 'Literal':
        return jsdoc.LiteralDoc({'value': me['value']})
    if me['type'] == 'Identifier':
        return ref(scope, me['name'])
    if me['type'] != 'MemberExpression':
        raise ValueError(me)
    return ref(
        m2r(me['object'], scope),
        utils._value(me['property'], strict=True)
    )

@attrs(slots=True)
class Declaration(object):
    id = attr(default=None)
    comments = attr(default=Factory(list))
@attrs(slots=True)
class ModuleContent(object):
    dependencies = attr(default=Factory(set))
    exports = attr(default=None)
    post = attr(default=Factory(list))
    def __iter__(self):
        yield self.dependencies
        yield self.exports
        yield self.post

@attrs # needs dict as it's replacing a ModuleProxy
class Nothing(object):
    name = attr()
    def __bool__(self):
        return False
    __nonzero__ = __bool__

class RefProxy(object):
    def __init__(self, r):
        self._ref = r
    def become(self, modules):
        s = self
        other = deref(self._ref) or Nothing(_name(self._ref))
        # ??? shouldn't all previous refs have been resolved?
        if isinstance(other, (RefProxy, ModuleProxy)):
            other = other.become(modules)
        self.__class__ = other.__class__
        self.__dict__ = other.__dict__
        return self
class ModuleProxy(object):
    def __init__(self, name):
        self._name = name

    # replace the ModuleProxy by the module's exports
    def become(self, modules):
        s = self
        m = modules[self._name].exports or Nothing(self._name)
        self.__class__ = m.__class__
        self.__dict__ = m.__dict__
        return self

jq = jsdoc.UnknownNS({
    'name': u'jQuery',
    'doc': u'<jQuery>',
})
window = jsdoc.UnknownNS({
    'doc': '<window>',
    'name': 'window',
})
BASE_SCOPE = {
    '_': jsdoc.UnknownNS({'doc': u'<underscore.js>', 'name': u'_'}),
    '$': jq, 'jQuery': jq,
    'nv': jsdoc.UnknownNS({
        'doc': u'<nvd3>',
        'name': u'nv',
    }),
    'window': window,
    'document': window.get_property('document'),
    'Date': jsdoc.ClassDoc({
        'name': u'Date',
        'doc': u'',
    }),
    'Backbone': jsdoc.UnknownNS({
        '_members': [
            ('Model', jsdoc.ClassDoc({
                'name': u'Model',
                'doc': u'',
            })),
            ('Collection', jsdoc.ClassDoc({
                'name': u'Collection',
                'doc': u'',
            })),
        ]
    }),
    'odoo': jsdoc.UnknownNS({
        'name': u'odoo',
        'doc': u"Odoo",
        '_members': [
            ('name', jsdoc.PropertyDoc({'name': u'csrf_token', 'type': u'{String}'})),
        ]
    }),
    'undefined': jsdoc.LiteralDoc({'name': u'undefined', 'value': None})
}

class ModuleExtractor(Visitor):
    def __init__(self, requirefunc):
        super(ModuleExtractor, self).__init__()
        self.requirefunc = requirefunc
        self.result = ModuleContent()
        self.scope = dict(BASE_SCOPE)
        self.declaration = None

    def enter_VariableDeclaration(self, node):
        self.declaration = Declaration(comments=node.get('comments'))
    def enter_VariableDeclarator(self, node):
        self.declaration.id = node['id']['name']
        self.scope[self.declaration.id] = ValueExtractor(
            self, self.declaration
        ).visit(node['init'] or [])
        self.declaration.id = None
        return SKIP
    def exit_VariableDeclaration(self, node):
        self.declaration = None

    # as the name denotes, AssignmentExpression is an *expression*, which
    # means at the module toplevel it is wrapped into an ExpressionStatement
    # which is where the comments get attached
    def enter_ExpressionStatement(self, node):
        self.declaration = Declaration(comments=node.get('comments'))
    def exit_ExpressionStatement(self, node):
        self.declaration = None
    def enter_AssignmentExpression(self, node):

        target = node['left']
        if target['type'] == 'Identifier':
            self.declaration.id = target['name']
            self.scope[self.declaration.id] = ValueExtractor(
                self, self.declaration
            ).visit(node['right'])
            self.declaration.id = None
            return SKIP

        if target['type'] != 'MemberExpression':
            raise ValueError("Unhandled assign to %s" % target['type'])

        # only assign to straight a.b.c patterns (OK and trivial literals)
        if target['computed'] and target['property']['type'] != 'Literal':
            return SKIP

        name = utils._value(target['property'], strict=True)
        if isinstance(name, type(u'')) and name.endswith('.extend'):
            return SKIP # ignore overwrite of .extend (WTF)
        self.declaration.id = name
        it = ValueExtractor(
            self, self.declaration
        ).visit(node['right'])
        self.declaration.id = None
        assert it, "assigned a non-value from %s to %s" % (node['right'], name)

        @self.result.post.append
        def _augment_module(modules):
            try:
                t = deref(m2r(target['object'], self.scope))
            except ValueError:
                return # f'n extension of global libraries garbage
            if not isinstance(t, jsdoc.ObjectDoc):
                # function Foo(){}; Foo.prototype = bar
                # fuck that yo
                return
            # TODO: note which module added this
            m = it
            if isinstance(m, jsdoc.LiteralDoc):
                m = jsdoc.PropertyDoc(m.to_dict())
            t.add_member(name, m)
        return SKIP

    def enter_FunctionDeclaration(self, node):
        funcname = node['id']['name']
        self.scope[funcname] = fn = jsdoc.parse_comments(
            node.get('comments'),
            jsdoc.FunctionDoc,
        )
        fn.parsed['guessed_function'] = node['id']['name']
        return SKIP

    def enter_ReturnStatement(self, node):
        self.declaration = Declaration(comments=node.get('comments'))
        if node['argument']:
            self.result.exports = ValueExtractor(
                self, self.declaration
            ).visit(node['argument'])
        self.declaration = None
        return SKIP

    def enter_CallExpression(self, node):
        if utils.match(node, {
            'callee': {
                'type': 'MemberExpression',
                'object': lambda n: (
                    n['type']  in ('Identifier', 'MemberExpression')
                    # _.str.include
                    and not utils._name(n).startswith('_')
                ),
                'property': {'name': 'include'},
            }
        }):
            target = RefProxy(m2r(node['callee']['object'], self.scope))
            target_name = utils._name(node['callee']['object'])
            items = ClassProcessor(self).visit(node['arguments'])
            @self.result.post.append
            def resolve_extension(modules):
                t = target.become(modules)
                if not isinstance(t, jsdoc.ClassDoc):
                    raise ValueError("include() subjects should be classes, %s is %s" % (target_name, type(t)))
                # TODO: note which module added these
                for it in items:
                    if isinstance(it, dict):
                        for member in it.values():
                            member.parsed['member'] = t
                            t.add_method(member)
                    else:
                        t.parsed.setdefault('mixes', []).append(it.become(modules))

        return SKIP

    def refify(self, node, also=None):
        it = m2r(node, self.scope)
        assert isinstance(it, ref), "Expected ref, got {}".format(it)
        px = RefProxy(it)
        @self.result.post.append
        def resolve(modules):
            p = px.become(modules)
            if also: also(p)
        return px

class ValueExtractor(Visitor):
    def __init__(self, parent, declaration=None):
        super(ValueExtractor, self).__init__()
        self.parent = parent
        self.declaration = declaration or Declaration()

    def enter_generic(self, node):
        self.result = jsdoc.parse_comments(
            self.declaration.comments,
            jsdoc.Unknown.from_(node['type'])
        )
        if self.declaration.id:
            self.result.set_name(self.declaration.id)
        return SKIP

    def enter_Literal(self, node):
        self.result = jsdoc.parse_comments(
            self.declaration.comments, jsdoc.LiteralDoc)
        if self.declaration.id:
            self.result.parsed['name'] = self.declaration.id
        self.result.parsed['value'] = node['value']
        return SKIP
    def enter_Identifier(self, node):
        self.result = self.parent.refify(node)
        return SKIP

    def enter_MemberExpression(self, node):
        self.result = RefProxy(ref(
            ValueExtractor(self.parent).visit(node['object']),
            utils._value(node['property'], strict=True)
        ))
        self.parent.result.post.append(self.result.become)
        return SKIP

    def enter_FunctionExpression(self, node):
        name, comments = astuple(self.declaration)
        self.result = jsdoc.parse_comments(comments, jsdoc.FunctionDoc)
        name = node['id']['name'] if node['id'] else name
        if name:
            self.result.parsed['guessed_function'] = name
        return SKIP

    def enter_NewExpression(self, node):
        comments = self.declaration.comments if self.declaration else node.get('comments')
        self.result = ns = jsdoc.parse_comments(comments, jsdoc.InstanceDoc)
        name = self.declaration.id if self.declaration else ''
        ns.parsed['name'] = name

        def _update_contents(cls):
            if not isinstance(cls, jsdoc.ClassDoc):
                return
            ns.parsed['cls'] = cls
        self.parent.refify(node['callee'], also=_update_contents)
        return SKIP

    def enter_ObjectExpression(self, node):
        self.result = obj = jsdoc.parse_comments(self.declaration.comments, jsdoc.ObjectDoc.from_parsed)
        if self.declaration.id:
            self.result.set_name(self.declaration.id)
        for n, p in MemberExtractor(parent=self.parent).visit(node['properties']).items():
            obj.add_member(n, p)
        return SKIP

    def enter_CallExpression(self, node):
        # require(a_module_name)
        if utils.match(node, {'callee': {'type': 'Identifier', 'name': self.parent.requirefunc}}):
            depname = node['arguments'][0]['value']
            # TODO: clean this up
            self.parent.result.dependencies.add(depname)
            self.result = ModuleProxy(name=depname)
            self.parent.result.post.append(self.result.become)

        # Class.extend(..mixins, {})
        elif utils.match(node, {
            'callee': {
                'type': 'MemberExpression',
                'object': lambda n: (
                    n['type'] in ('Identifier', 'MemberExpression')
                    # $.extend, $.fn.extend, _.extend
                    and not utils._name(n).startswith(('_', '$'))
                ),
                'property': {'name': 'extend'},
            },
        }):  # creates a new class, but may not actually return it
            obj = node['callee']['object']
            varname, comments = astuple(self.declaration)
            self.result = cls = jsdoc.parse_comments(comments, jsdoc.ClassDoc)
            cls.parsed['extends'] = self.parent.refify(obj)
            if varname:
                cls.parsed['class'] = varname
            items = ClassProcessor(self.parent).visit(node['arguments'])

            @self.parent.result.post.append
            def add_to_class(modules):
                for item in items:
                    if isinstance(item, dict):
                        # methods/attributes
                        for method in item.values():
                            method.parsed['member'] = cls
                            cls.add_method(method)
                    else:
                        cls.parsed.setdefault('mixes', []).append(item)

        # other function calls
        else:
            self.result = jsdoc.parse_comments(self.declaration.comments, jsdoc.guess)

        return SKIP

class ClassProcessor(Visitor):
    def __init__(self, parent):
        super(ClassProcessor, self).__init__()
        self.result = []
        self.parent = parent

    def enter_generic(self, node):
        self.result.append(self.parent.refify(node))
        return SKIP
    def enter_ObjectExpression(self, node):
        self.result.append(MemberExtractor(parent=self.parent, for_class=True).visit(node['properties']))
        return SKIP

String = type(u'')
class MemberExtractor(Visitor):
    def __init__(self, parent, for_class=False):
        super(MemberExtractor, self).__init__()
        self.result = collections.OrderedDict()
        self.parent = parent
        self.for_class = for_class

    def enter_Property(self, node):
        name = utils._value(node['key'])
        prop = ValueExtractor(
            self.parent,
            Declaration(id=name, comments=node.get('comments'))
        ).visit(node['value'])

        if isinstance(prop, jsdoc.LiteralDoc):
            prop = jsdoc.PropertyDoc(prop.to_dict())

        # ValueExtractor can return a Ref, maybe this should be sent as part
        # of the decl/comments?
        if name.startswith('_') and hasattr(prop, 'parsed'):
            prop.parsed['private'] = True
        self.result[name] = prop

        return SKIP
