odoo.define('card_reader.MagneticParser', function (require) {
"use strict";

var Class   = require('web.Class');
var Model   = require('web.Model');
var session = require('web.session');
var core    = require('web.core');
var screens = require('point_of_sale.screens');
var gui     = require('point_of_sale.gui');
var pos_model = require('point_of_sale.models');

var Qweb    = core.qweb;
var _t      = core._t;

Qweb.add_template('/card_reader/static/src/xml/templates.xml');

var BarcodeParser = require('barcodes.BarcodeParser');
var PopupWidget = require('point_of_sale.popups');
var ScreenWidget = screens.ScreenWidget;
var PaymentScreenWidget = screens.PaymentScreenWidget;

var onlinePaymentJournal = [];

var allowOnlinePayment = function (pos) {
    if (onlinePaymentJournal.length) {
        return true;
    }
    $.each(pos.journals, function (i, val) {
        if (val.card_reader_config_id) {
            onlinePaymentJournal.push({label:val.display_name, item:val.id});
        }
    });
    return onlinePaymentJournal.length;
};

// Popup declaration to ask for confirmation before an electronic payment
var PaymentConfirmPopupWidget = PopupWidget.extend({
    template: 'PaymentConfirmPopupWidget',
    show: function (options) {
        this._super(options);
    }
});

function getCashRegisterByJournalID (cashRegisters, journal_id) {
    var cashRegisterReturn;

    $.each(cashRegisters, function (index, cashRegister) {
        if (cashRegister.journal_id[0] == journal_id) {
            cashRegisterReturn = cashRegister;
        }
    });

    return cashRegisterReturn;
}

function decodeMercuryResponse (data) {
    // get rid of xml version declaration and just keep the RStream
    // from the response because the xml contains two version
    // declarations. One for the SOAP, and one for the content. Maybe
    // we should unpack the SOAP layer in python?
    data = data.replace(/.*<\?xml version="1.0"\?>/, "");
    data = data.replace(/<\/CreditTransactionResult>.*/, "");

    var xml = $($.parseXML(data));
    var cmd_response = xml.find("CmdResponse");
    var tran_response = xml.find("TranResponse");

    return {
        status: cmd_response.find("CmdStatus").text(),
        message: cmd_response.find("TextResponse").text(),
        error: cmd_response.find("DSIXReturnCode").text(),
        auth_code: tran_response.find("AuthCode").text(),
        acq_ref_data: tran_response.find("AcqRefData").text(),
        process_data: tran_response.find("ProcessData").text(),
        invoice_no: tran_response.find("InvoiceNo").text(),
        ref_no: tran_response.find("RefNo").text(),
        record_no: tran_response.find("RecordNo").text(),
        purchase: parseFloat(tran_response.find("Purchase").text()),
        authorize: parseFloat(tran_response.find("Authorize").text()),
    };
}

var _paylineproto = pos_model.Paymentline.prototype;

pos_model.Paymentline = pos_model.Paymentline.extend({
    initialize: function () {
        _paylineproto.initialize.apply(this, arguments);
        this.paid = false;
        this.mercury_data = false;
    },
    init_from_JSON: function (json) {
        this.paid = json.paid;
        this.mercury_data = json.mercury_data;
        _paylineproto.init_from_JSON.apply(this, arguments);
    },
    export_as_JSON: function () {
        return _.extend(_paylineproto.export_as_JSON.apply(this, arguments), {paid: this.paid, mercury_data: this.mercury_data});
    }
});

// Lookup table to store status and error messages
var lookUpCodeTransaction = {
    'Approved': {
        '000000': _t('Transaction approved'),
    },
    'TimeoutError': {
        '001006': _t('Global API Not Initialized'),
        '001007': _t('Timeout on Response'),
        '003003': _t('Socket Error sending request'),
        '003004': _t('Socket already open or in use'),
        '003005': _t('Socket Creation Failed'),
        '003006': _t('Socket Connection Failed'),
        '003007': _t('Connection Lost'),
        '003008': _t('TCP/IP Failed to Initialize'),
        '003010': _t('Time Out waiting for server response'),
        '003011': _t('Connect Cancelled'),
        '003053': _t('Initialize Failed'),
        '009999': _t('Unknown Error'),
    },
    'FatalError': {
        '-1':     _t('Timeout error'),
        '000000': _t('Insufficient balance on your card'),
        '001001': _t('General Failure'),
        '001003': _t('Invalid Command Format'),
        '001004': _t('Insufficient Fields'),
        '001011': _t('Empty Command String'),
        '002000': _t('Password Verified'),
        '002001': _t('Queue Full'),
        '002002': _t('Password Failed – Disconnecting'),
        '002003': _t('System Going Offline'),
        '002004': _t('Disconnecting Socket'),
        '002006': _t('Refused ‘Max Connections’'),
        '002008': _t('Duplicate Serial Number Detected'),
        '002009': _t('Password Failed (Client / Server)'),
        '002010': _t('Password failed (Challenge / Response)'),
        '002011': _t('Internal Server Error – Call Provider'),
        '003002': _t('In Process with server'),
        '003009': _t('Control failed to find branded serial (password lookup failed)'),
        '003012': _t('128 bit CryptoAPI failed'),
        '003014': _t('Threaded Auth Started Expect Response'),
        '003017': _t('Failed to start Event Thread.'),
        '003050': _t('XML Parse Error'),
        '003051': _t('All Connections Failed'),
        '003052': _t('Server Login Failed'),
        '004001': _t('Global Response Length Error (Too Short)'),
        '004002': _t('Unable to Parse Response from Global (Indistinguishable)'),
        '004003': _t('Global String Error'),
        '004004': _t('Weak Encryption Request Not Supported'),
        '004005': _t('Clear Text Request Not Supported'),
        '004010': _t('Unrecognized Request Format'),
        '004011': _t('Error Occurred While Decrypting Request'),
        '004017': _t('Invalid Check Digit'),
        '004018': _t('Merchant ID Missing'),
        '004019': _t('TStream Type Missing'),
        '004020': _t('Could Not Encrypt Response- Call Provider'),
        '100201': _t('Invalid Transaction Type'),
        '100202': _t('Invalid Operator ID'),
        '100203': _t('Invalid Memo'),
        '100204': _t('Invalid Account Number'),
        '100205': _t('Invalid Expiration Date'),
        '100206': _t('Invalid Authorization Code'),
        '100207': _t('Invalid Authorization Code'),
        '100208': _t('Invalid Authorization Amount'),
        '100209': _t('Invalid Cash Back Amount'),
        '100210': _t('Invalid Gratuity Amount'),
        '100211': _t('Invalid Purchase Amount'),
        '100212': _t('Invalid Magnetic Stripe Data'),
        '100213': _t('Invalid PIN Block Data'),
        '100214': _t('Invalid Derived Key Data'),
        '100215': _t('Invalid State Code'),
        '100216': _t('Invalid Date of Birth'),
        '100217': _t('Invalid Check Type'),
        '100218': _t('Invalid Routing Number'),
        '100219': _t('Invalid TranCode'),
        '100220': _t('Invalid Merchant ID'),
        '100221': _t('Invalid TStream Type'),
        '100222': _t('Invalid Batch Number'),
        '100223': _t('Invalid Batch Item Count'),
        '100224': _t('Invalid MICR Input Type'),
        '100225': _t('Invalid Driver’s License'),
        '100226': _t('Invalid Sequence Number'),
        '100227': _t('Invalid Pass Data'),
        '100228': _t('Invalid Card Type'),
    },
};

// Popup to show all transaction state for the payment.

var PaymentTransactionPopupWidget = PopupWidget.extend({
    template: 'PaymentTransactionPopupWidget',
    show: function (options) {
        var self = this;
        this._super(options);
        options.transaction.then(function (data) {
            if (data.status == "Error" || data.status == "Declined") {
                if (lookUpCodeTransaction["TimeoutError"][data.error]) { // Not fatal, retry
                    data.message = "Error " + data.error + ": " + lookUpCodeTransaction["TimeoutError"][data.error] + ".<br/><br/>Retrying...";
                } else if (lookUpCodeTransaction["FatalError"][data.error]) { // Fatal, stop
                    data.message = "Error " + data.error + ": " + lookUpCodeTransaction["FatalError"][data.error];
                    self.close();
                    self.$el.find('.popup').append('<div class="footer"><div class="button cancel">Ok</div></div>');
                }
            } else if (data.status == "Success" || data.status == "Approved") {
                if (data.partial) {
                    data.message = "Partially approved";
                    self.close();
                    self.$el.find('.popup').append('<div class="footer"><div class="button cancel">Ok</div></div>');
                } else {
                    data.message = lookUpCodeTransaction["Approved"][data.error];
                    setTimeout(function () {
                        self.gui.close_popup();
                    }, 2000);
                }
            }

            self.$el.find('p.body').html(data.message);

        }).progress(function (data) {
            var to_display = '';

            if (data.error) {
                to_display = data.status + ' ' + data.error + '<br/><br/>' + data.message;
            } else {
                to_display = data.status + '<br/><br/>' + data.message;
            }

            self.$el.find('p.body').html(to_display);
        });
    }
});

gui.define_popup({name:'payment-confirm', widget: PaymentConfirmPopupWidget});
gui.define_popup({name:'payment-transaction', widget: PaymentTransactionPopupWidget});

// On all screens, if a card is swipped, return a popup error.
ScreenWidget.include({
    credit_error_action: function () {
        this.gui.show_popup('error-barcode','Go to payment screen to use cards');
    },

    show: function () {
        this._super();
        if(allowOnlinePayment(this.pos)) {
            this.pos.barcode_reader.set_action_callback('Credit', _.bind(this.credit_error_action, this));
        }
    }
});

// On Payment screen, allow electronic payments
PaymentScreenWidget.include({
    // Regular expression to identify and extract data from the track 1 & 2 of the magnetic code
    _track1:/%B?([0-9]*)\^([A-Z\/ -_]*)\^([0-9]{4})(.{3})([^?]+)\?/,
    _track2:/\;([0-9]+)=([0-9]{4})(.{3})([^?]+)\?/,

    // Extract data from a track list to a track dictionnary
    _decode_track: function(track_list) {

        if(track_list < 6) return {};

        return {
            'private'       : track_list.pop(),
            'service_code'  : track_list.pop(),
            'validity'      : track_list.pop(),
            'name'          : track_list.pop(),
            'card_number'   : track_list.pop(),
            'original'      : track_list.pop(),
        };

    },
    // Extract data from crypted track list to a track dictionnary
    _decode_encrypted_data: function (code_list) {
        if(code_list < 13) return {};
        var encrypted_data = {
            'format_code'           : code_list.pop(),
            'enc_crc'               : code_list.pop(),
            'clear_text_crc'        : code_list.pop(),
        };

        if(code_list.lenght > 10) {
            encrypted_data['encryption_counter'] = code_list.pop();
        }

        _.extend(encrypted_data, {
            'dukpt_serial_n'        : code_list.pop(),
            'enc_session_id'        : code_list.pop(),
            'device_serial'         : code_list.pop(),
            'magneprint_data'       : code_list.pop(),
            'magneprint_status'     : code_list.pop(),
            'enc_track3'            : code_list.pop(),
            'enc_track2'            : code_list.pop(),
            'enc_track1'            : code_list.pop(),
            'reader_enc_status'     : code_list.pop(),
        });
        return encrypted_data;
    },

    // Handler to manage the card reader string
    credit_code_transaction: function (parsed_result) {
        if(!allowOnlinePayment(this.pos)) {
            return;
        }

        var def = new $.Deferred();
        var self = this;

        // show the transaction popup.
        // the transaction deferred is used to update transaction status
        this.gui.show_popup('payment-transaction', {
            transaction: def
        });

        // Construct a dictionnary to store all data from the magnetic card
        var transaction = {
            track1: this._decode_track(parsed_result.code.match(this._track1)),
            track2: this._decode_track(parsed_result.code.match(this._track2)),
            track3: {},
            encrypted_data: this._decode_encrypted_data(parsed_result.code.split('|')),
        };

        // Extends the dictionnary with needed client side data to complete the request transaction

        _.extend(transaction, {
            'transaction_type'  : 'Credit',
            'transaction_code'  : 'Sale',
            'invoice_no'        : self.pos.get_order().sequence_number,
            'purchase'          : parsed_result.total,
            'journal_id'        : parsed_result.journal_id,
        });

        def.notify({
            error: 0,
            status: 'Waiting',
            message: 'Handling transaction...',
        });

        var rpc_def = session.rpc("/pos/send_payment_transaction", transaction)
                .done(function (data) {
                    console.log(data); // todo

                    if (! self.waiting_on_payment_response) {
                        return;
                    }
                    self.waiting_on_payment_response = false;

                    var response = decodeMercuryResponse(data);
                    response.journal_id = parsed_result.journal_id;

                    if (response.status === 'Approved') {
                        // If the payment is approved, add a payment line
                        var order = self.pos.get_order();
                        order.add_paymentline(getCashRegisterByJournalID(self.pos.cashregisters, parsed_result.journal_id));
                        order.selected_paymentline.paid = true;
                        order.selected_paymentline.amount = response.authorize;
                        order.selected_paymentline.mercury_data = response; // used to reverse transactions
                        self.order_changes();
                        self.reset_input();
                        self.render_paymentlines();
                    }

                    def.resolve({
                        status: response.status,
                        error: response.error,
                        partial: response.message === "PARTIAL AP" && response.authorize < response.purchase
                    });

                    // if a error related to timeout or connectivity issues arised, then retry the same transaction
                    if (response.status == "Error" && lookUpCodeTransaction["TimeoutError"][response.error]) {
                        self.credit_code_transaction(parsed_result);
                    }

                }).fail(function (data) {
                    def.reject({
                        status: 'Error',
                        error: '-1',
                    });
                });

        // if not receiving a response for > 60 seconds, we should retry
        if (self.waiting_on_payment_response) {
            setTimeout(function () {
                if (rpc_def.state() == "pending") {
                    self.credit_code_transaction(parsed_result);
                }
            }, 65000);
        }
    },
    credit_code_cancel: function () {
        return;
    },

    credit_code_action: function (parsed_result) {
        self = this;
        parsed_result.total = this.pos.get_order().get_due();
        self.waiting_on_payment_response = true;

        if (parsed_result.total) {
            if (onlinePaymentJournal.length === 1) {
                parsed_result.journal_id = onlinePaymentJournal[0].item;
                self.credit_code_transaction(parsed_result);
            } else { // this is for supporting another payment system like mercury
                this.gui.show_popup('selection',{
                    title:   'Pay ' + parsed_result.total.toFixed(2) + ' with : ',
                    list:    onlinePaymentJournal,
                    confirm: function (item) {
                        parsed_result.journal_id = item;
                        self.credit_code_transaction(parsed_result);
                    },
                    cancel:  self.credit_code_cancel,
                });
            }
        }
        else {
            // display error popup
        }
    },

    do_reversal: function (mercury_data, is_voidsale) {
        var def = new $.Deferred();
        var self = this;

        // show the transaction popup.
        // the transaction deferred is used to update transaction status
        this.gui.show_popup('payment-transaction', {
            transaction: def
        });

        var request_data = _.extend({
            'transaction_type'  : 'Credit',
            'transaction_code'  : 'VoidSaleByRecordNo',
        }, mercury_data);

        var message = "";
        var rpc_url = "/pos/";

        if (is_voidsale) {
            message = "Reversal failed, sending VoidSale...";
            rpc_url += "send_voidsale";
        } else {
            message = "Sending reversal...";
            rpc_url += "send_reversal";
        }

        def.notify({
            error: 0,
            status: 'Waiting',
            message: message,
        });

        session.rpc(rpc_url, request_data)
            .done(function (data) {
                console.log(data); // todo
                var response = decodeMercuryResponse(data);

                if (! is_voidsale) {
                    if (response.status != 'Approved' || response.message != 'REVERSED') {
                        // reversal was not successful, send voidsale
                        self.do_reversal(mercury_data, true);
                    } else {
                        // reversal was successful
                        def.resolve({
                            status: response.status,
                            error: response.error,
                            message: response.message,
                        });
                    }
                } else {
                    // voidsale failed, nothing more we can do
                    def.resolve({
                        status: response.status,
                        error: response.error,
                        message: response.message,
                    });
                }

            })  .fail(function (data) {
                def.reject({
                    status: 'Odoo Error',
                    error: '-1',
                    message: 'Impossible to contact the proxy, please retry ...',
                });
            });
    },

    click_delete_paymentline: function (cid) {
        var lines = this.pos.get_order().get_paymentlines();

        for ( var i = 0; i < lines.length; i++ ) {
            if (lines[i].cid === cid && lines[i].mercury_data) {
                this.do_reversal(lines[i].mercury_data, false);
            }
        }

        this._super(cid);
    },

    show: function () {
        this._super();
        if (allowOnlinePayment(this.pos)) {
            this.pos.barcode_reader.set_action_callback('Credit', _.bind(this.credit_code_action, this));
        }
    }
});

window.test_card_reader = {
    MagneticParser: BarcodeParser,
    ScreenWidget: ScreenWidget,
    QWeb : Qweb,
};

return {
    MagneticParser: BarcodeParser,
    ScreenWidget: ScreenWidget,
};

});
