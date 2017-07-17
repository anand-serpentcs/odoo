odoo.define('website_sale.add_product', function (require) {
'use strict';

var core = require('web.core');
var wUtils = require('website.utils');
var WebsiteNewMenu = require('website.newMenu');

var _t = core._t;

WebsiteNewMenu.include({
    actions: _.extend({}, WebsiteNewMenu.prototype.actions || {}, {
        new_product: '_createNewProduct',
    }),

    //----------------------------------------------------------------------
    // Actions
    //----------------------------------------------------------------------

    /**
     * Asks the user information about a new product to create, then creates it
     * and redirects the user to this new page.
     *
     * @private
     * @returns {Deferred} Unresolved if the product is created as there will be
     *                     a redirection
     */
    _createNewProduct: function () {
        var self = this;
        var def = $.Deferred();
        wUtils.prompt({
            id: "editor_new_product",
            window_title: _t("New Product"),
            input: "Product Name",
        }).then(function (name) {
            self._rpc({
                route: '/shop/add_product',
                params: {
                    name: name,
                },
            }).then(function (url) {
                window.location.href = url;
            });
        }, def.resolve.bind(def));
        return def;
    },
});
});

//==============================================================================

odoo.define('website_sale.editor', function (require) {
'use strict';

require('web.dom_ready');
var options = require('web_editor.snippets.options');
var widget = require('web_editor.widget');
var web_editor = require('web_editor.editor');

var toDelete = [];

if (!$('.js_sale').length) {
    return $.Deferred().reject("DOM doesn't contain '.js_sale'");
}

$('.oe_website_sale').on('click', '.oe_currency_value:o_editable', function (ev) {
    $(ev.currentTarget).selectContent();
});

$('#product_detail').on('click', '.o_img_delete', function (e){
    var $image = e.target.closest('[data-img-id]');
    var id = $image.dataset.imgId;
    if (id) {
        toDelete.push(parseInt(id));
    }
    $image.remove();

});

$('.oe_website_sale').on('click', '.add_img', function (e){
    if($('body.editor_enable').length) {
        var $this = e.target.closest('li');
        var $image = $("<img/>");

        var editor = new widget.MediaDialog(null, {only_images: true}, $image, $image[0]).open();
        var index = parseInt($this.dataset.slideTo);

        editor.on("save", this, function (event) {
            var $li = $('<li/>').attr('data-target', '#o-carousel-product').attr('data-slide-to', index);
            $image.addClass('img img-responsive').appendTo($li);
            $this.dataset.slideTo = index + 1;
            $li.insertBefore($this);
            $li.addClass('new_img');
        });
    }
});

web_editor.Class.include({
    save: function () {
        var self = _.clone(this);
        var images = $('.new_img');
        var id = $('#product_detail').attr('data-id');

        var imageDefs = [];
        _.each(images, function (image) {
            var def = $.Deferred();
            var img = new Image();
            img.onload = function () {
                var canvas = document.createElement("CANVAS");
                var ctx = canvas.getContext("2d");
                canvas.width = this.width;
                canvas.height = this.height;
                ctx.drawImage(this, 0, 0);
                path = canvas.toDataURL("image/jpeg");
                canvas = null;
                var path = path.replace(/^data:image\/[a-z]+;base64,/, "");
                this._rpc({
                    model: 'product.image',
                    method: 'create',
                    args: [{'product_tmpl_id': id, 'image': path}],
                }).then( function () {
                    def.resolve();
                });
            }
            img.src = image.children[0].src;
            imageDefs.push(def);
        });
        if (toDelete.length) {
            var def = $.Deferred();
            this._rpc({
                model: 'product.image',
                method: 'unlink',
                args: [toDelete],
            }).then( function () {
                def.resolve();
            });
            imageDefs.push(def);
        }

        $.when.apply($, imageDefs).then(function (){
            return self._super.apply(self, arguments);
        });
    }
});

options.registry.website_sale = options.Class.extend({
    /**
     * @override
     */
    start: function () {
        var self = this;
        this.product_tmpl_id = parseInt(this.$target.find('[data-oe-model="product.template"]').data('oe-id'));

        var size_x = parseInt(this.$target.attr("colspan") || 1);
        var size_y = parseInt(this.$target.attr("rowspan") || 1);

        var $size = this.$el.find('ul[name="size"]');
        var $select = $size.find('tr:eq(0) td:lt('+size_x+')');
        if (size_y >= 2) $select = $select.add($size.find('tr:eq(1) td:lt('+size_x+')'));
        if (size_y >= 3) $select = $select.add($size.find('tr:eq(2) td:lt('+size_x+')'));
        if (size_y >= 4) $select = $select.add($size.find('tr:eq(3) td:lt('+size_x+')'));
        $select.addClass("selected");

        this._rpc({
            model: 'product.style',
            method: 'search_read',
        }).then(function (data) {
            var $ul = self.$el.find('ul[name="style"]');
            for (var k in data) {
                $ul.append(
                    $('<li data-style="'+data[k]['id']+'" data-toggle-class="'+data[k]['html_class']+'" data-no-preview="true"/>')
                        .append( $('<a/>').text(data[k]['name']) ));
            }
            self._setActive();
        });

        this.bind_resize();
    },
    reload: function () {
        if (window.location.href.match(/\?enable_editor/)) {
            window.location.reload();
        } else {
            window.location.href = window.location.href.replace(/\?(enable_editor=1&)?|#.*|$/, '?enable_editor=1&');
        }
    },
    bind_resize: function () {
        var self = this;
        this.$el.on('mouseenter', 'ul[name="size"] table', function (event) {
            $(event.currentTarget).addClass("oe_hover");
        });
        this.$el.on('mouseleave', 'ul[name="size"] table', function (event) {
            $(event.currentTarget).removeClass("oe_hover");
        });
        this.$el.on('mouseover', 'ul[name="size"] td', function (event) {
            var $td = $(event.currentTarget);
            var $table = $td.closest("table");
            var x = $td.index()+1;
            var y = $td.parent().index()+1;

            var tr = [];
            for (var yi=0; yi<y; yi++) tr.push("tr:eq("+yi+")");
            var $select_tr = $table.find(tr.join(","));
            var td = [];
            for (var xi=0; xi<x; xi++) td.push("td:eq("+xi+")");
            var $select_td = $select_tr.find(td.join(","));

            $table.find("td").removeClass("select");
            $select_td.addClass("select");
        });
        this.$el.on('click', 'ul[name="size"] td', function (event) {
            var $td = $(event.currentTarget);
            var x = $td.index()+1;
            var y = $td.parent().index()+1;
            self._rpc({
                route: '/shop/change_size',
                params: {
                    id: self.product_tmpl_id,
                    x: x,
                    y: y,
                },
            }).then(self.reload);
        });
    },
    style: function (previewMode, value, $li) {
        this._rpc({
            route: '/shop/change_styles',
            params: {
                id: this.product_tmpl_id,
                style_id: value,
            },
        });
    },
    go_to: function (previewMode, value) {
        this._rpc({
            route: '/shop/change_sequence',
            params: {
                id: this.product_tmpl_id,
                sequence: value,
            },
        }).then(this.reload);
    }
});
});
