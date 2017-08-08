odoo.define('barcodes.tests', function (require) {
"use strict";

var barcodeEvents = require('barcodes.BarcodeEvents');

var testUtils = require('web.test_utils');
var FormView = require('web.FormView');

var createView = testUtils.createView;
var triggerKeypressEvent = testUtils.triggerKeypressEvent;

QUnit.module('Barcodes', {
    beforeEach: function () {
        this.data = {
            product: {
                fields: {
                    name: {string : "Product name", type: "char"},
                    int_field: {string : "Integer", type: "integer"},
                },
                records: [
                    {id: 1, name: "iPad Mini"},
                    {id: 2, name: "Mouse, Optical"},
                ],
            },
        };
    }
});

QUnit.test('edit, save and cancel buttons', function (assert) {
    assert.expect(6);

    var form = createView({
        View: FormView,
        model: 'product',
        data: this.data,
        arch: '<form><field name="display_name"/></form>',
        mockRPC: function (route, args) {
            if (args.method === 'write') {
                assert.step('save');
            }
            return this._super.apply(this, arguments);
        },
        res_id: 1,
    });

    // O-CMD.EDIT
    _.each(["O","-","C","M","D",".","E","D","I","T","Enter"], triggerKeypressEvent);
    assert.strictEqual(form.$(".o_form_editable").length, 1,
        "should have switched to 'edit' mode");
    // dummy change to check that it actually saves
    form.$('.o_field_widget').val('test').trigger('input');
    // O-CMD.SAVE
    _.each(["O","-","C","M","D",".","S","A","V","E","Enter"], triggerKeypressEvent);
    assert.strictEqual(form.$(".o_form_readonly").length, 1,
        "should have switched to 'readonly' mode");
    assert.verifySteps(['save'], 'should have saved');

    // O-CMD.EDIT
    _.each(["O","-","C","M","D",".","E","D","I","T","Enter"], triggerKeypressEvent);
    // dummy change to check that it correctly discards
    form.$('.o_field_widget').val('test').trigger('input');
    // O-CMD.CANCEL
    _.each(["O","-","C","M","D",".","C","A","N","C","E","L","Enter"], triggerKeypressEvent);
    assert.strictEqual(form.$(".o_form_readonly").length, 1,
        "should have switched to 'readonly' mode");
    assert.verifySteps(['save'], 'should not have saved');

    form.destroy();
});

QUnit.test('pager buttons', function (assert) {
    assert.expect(3);

    var form = createView({
        View: FormView,
        model: 'product',
        data: this.data,
        arch: '<form><field name="display_name"/></form>',
        res_id: 1,
        viewOptions: {
            ids: [1, 2],
            index: 0,
        },
    });

    assert.strictEqual(form.$('.o_field_widget').text(), 'iPad Mini');
    // O-CMD.PAGER-NEXT
    _.each(["O","-","C","M","D",".","P","A","G","E","R","-","N","E","X","T","Enter"], triggerKeypressEvent);
    assert.strictEqual(form.$('.o_field_widget').text(), 'Mouse, Optical');
    // O-CMD.PAGER-PREV
    _.each(["O","-","C","M","D",".","P","A","G","E","R","-","P","R","E","V","Enter"], triggerKeypressEvent);
    assert.strictEqual(form.$('.o_field_widget').text(), 'iPad Mini');

    form.destroy();
});

QUnit.test('widget field_float_scannable', function (assert) {
    var done = assert.async();
    assert.expect(11);

    var delay = barcodeEvents.BarcodeEvents.max_time_between_keys_in_ms;
    barcodeEvents.BarcodeEvents.max_time_between_keys_in_ms = 0;

    this.data.product.records[0].int_field = 4;
    this.data.product.onchanges = {
        int_field: function () {},
    };

    var form = createView({
        View: FormView,
        model: 'product',
        data: this.data,
        arch: '<form>' +
                    '<field name="display_name"/>' +
                    '<field name="int_field" widget="field_float_scannable"/>' +
                '</form>',
        mockRPC: function (route, args) {
            if (args.method === 'onchange') {
                assert.step('onchange');
                assert.strictEqual(args.args[1].int_field, 426,
                    "should send correct value for int_field");
            }
            return this._super.apply(this, arguments);
        },
        fieldDebounce: 1000,
        res_id: 1,
    });

    assert.strictEqual(form.$('.o_field_widget[name=int_field]').text(), '4',
        "should display the correct value in readonly");

    form.$buttons.find('.o_form_button_edit').click();

    assert.strictEqual(form.$('.o_field_widget[name=int_field]').val(), '4',
        "should display the correct value in edit");

    // simulates keypress events in the input to replace 0.00 by 26 (should not trigger onchanges)
    form.$('.o_field_widget[name=int_field]').focus();
    assert.strictEqual(form.$('.o_field_widget[name=int_field]').get(0), document.activeElement,
        "int field should be focused");
    form.$('.o_field_widget[name=int_field]').trigger({type: 'keypress', which: 50, keyCode: 50}); // 2
    assert.strictEqual(form.$('.o_field_widget[name=int_field]').get(0), document.activeElement,
        "int field should still be focused");
    form.$('.o_field_widget[name=int_field]').trigger({type: 'keypress', which: 54, keyCode: 54}); // 6
    assert.strictEqual(form.$('.o_field_widget[name=int_field]').get(0), document.activeElement,
        "int field should still be focused");

    setTimeout(function () {
        assert.strictEqual(form.$('.o_field_widget[name=int_field]').val(), '426',
            "should display the correct value in edit");
        assert.strictEqual(form.$('.o_field_widget[name=int_field]').get(0), document.activeElement,
        "int field should still be focused");

        assert.verifySteps([], 'should not have done any onchange RPC');

        form.$('.o_field_widget[name=int_field]').trigger('change'); // should trigger the onchange

        assert.verifySteps(['onchange'], 'should have done the onchange RPC');

        form.destroy();
        barcodeEvents.BarcodeEvents.max_time_between_keys_in_ms = delay;
        done();
    });

});

});
