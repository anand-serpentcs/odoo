odoo.define('website.snippets.animation', function (require) {
'use strict';

var ajax = require('web.ajax');
var core = require('web.core');
var base = require('web_editor.base');
var animation = require('web_editor.snippets.animation');

var qweb = core.qweb;

var ids_or_xml_ids = _.uniq($("[data-oe-call]").map(function () {return $(this).data('oe-call');}).get());
if (ids_or_xml_ids.length) {
    ajax.jsonRpc('/website/multi_render', 'call', {
            'ids_or_xml_ids': ids_or_xml_ids
        }).then(function (data) {
            for (var k in data) {
                var $data = $(data[k]).addClass('o_block_'+k);
                $("[data-oe-call='"+k+"']").each(function () {
                    $(this).replaceWith($data.clone());
                });
            }
        });
}

animation.registry.slider = animation.Class.extend({
    selector: ".carousel",
    start: function () {
        this.$target.carousel();
    },
    stop: function () {
        this.$target.carousel('pause');
        this.$target.removeData("bs.carousel");
    },
});

animation.registry.parallax = animation.Class.extend({
    selector: ".parallax",

    start: function () {
        _.defer((function () { this.set_values(); }).bind(this));
        $(window).on("scroll.animation_parallax", _.throttle(this.on_scroll.bind(this), 10))
                 .on("resize.animation_parallax", _.debounce(this.set_values.bind(this), 500));

        return this._super.apply(this, arguments);
    },
    stop: function () {
        $(window).off(".animation_parallax");
    },

    set_values: function () {
        var self = this;
        this.speed = parseFloat(self.$target.attr("data-scroll-background-ratio") || 0);
        this.offset = 0;

        if (this.speed === 1 || this.$target.css("background-image") === "none") {
            this.$target.css("background-attachment", "fixed").css("background-position", "0px 0px");
            return;
        }

        this.$target.css("background-attachment", "scroll");

        var img = new Image();
        img.onload = function () {
            var offset = 0;
            var padding =  parseInt($(document.body).css("padding-top"));
            if (self.speed > 1) {
                var inner_offset = - self.$target.outerHeight() + this.height / this.width * document.body.clientWidth;
                var outer_offset = self.$target.offset().top - (document.body.clientHeight - self.$target.outerHeight()) - padding;
                offset = - outer_offset * self.speed + inner_offset;
            } else {
                offset = - self.$target.offset().top * self.speed;
            }
            self.offset = offset > 0 ? 0 : offset;
            self.on_scroll();
        };
        img.src = this.$target.css("background-image").replace(/url\(['"]*|['"]*\)/g, "");
    },

    on_scroll: function () {
        if (this.speed === 1) return;
        var top = this.offset + window.scrollY * this.speed;
        this.$target.css("background-position", "0px " + top + "px");
    },
});

animation.registry.share = animation.Class.extend({
    selector: ".oe_share",
    start: function () {
        var url_regex = /(\?(?:|.*&)(?:u|url|body)=)(.*?)(&|#|$)/;
        var title_regex = /(\?(?:|.*&)(?:title|text|subject)=)(.*?)(&|#|$)/;
        var url = encodeURIComponent(window.location.href);
        var title = encodeURIComponent($("title").text());
        this.$("a").each(function () {
            var $a = $(this);
            $a.attr("href", function(i, href) {
                return href.replace(url_regex, function (match, a, b, c) {
                    return a + url + c;
                }).replace(title_regex, function (match, a, b, c) {
                    return a + title + c;
                });
            });
            if ($a.attr("target") && $a.attr("target").match(/_blank/i) && !$a.closest('.o_editable').length) {
                $a.on('click', function () {
                    window.open(this.href,'','menubar=no,toolbar=no,resizable=yes,scrollbars=yes,height=550,width=600');
                    return false;
                });
            }
        });
    }
});

animation.registry.media_video = animation.Class.extend({
    selector: ".media_iframe_video",
    start: function () {
        if (!this.$target.has('> iframe').length) {
            var editor = '<div class="css_editable_mode_display">&nbsp;</div>';
            var size = '<div class="media_iframe_video_size">&nbsp;</div>';
            this.$target.html(editor+size+'<iframe src="'+_.escape(this.$target.data("src"))+'" frameborder="0" allowfullscreen="allowfullscreen"></iframe>');
        }
    },
});

animation.registry.ul = animation.Class.extend({
    selector: "ul.o_ul_folded, ol.o_ul_folded",
    start: function (editable_mode) {
        this.$('.o_ul_toggle_self').off('click').on('click', function (event) {
            $(this).toggleClass('o_open');
            $(this).closest('li').find('ul,ol').toggleClass('o_close');
            event.preventDefault();
        });

        this.$('.o_ul_toggle_next').off('click').on('click', function (event) {
            $(this).toggleClass('o_open');
            $(this).closest('li').next().toggleClass('o_close');
            event.preventDefault();
        });
    },
});

/**
 * This is a fix for apple device (<= IPhone 4, IPad 2)
 * Standard bootstrap requires data-toggle='collapse' element to be <a/> tags. Unfortunatly one snippet uses a
 * <div/> tag instead. The fix forces an empty click handler on these div, which allows standard bootstrap to work.
 *
 * This should be removed in a future odoo snippets refactoring.
 */
animation.registry._fix_apple_collapse = animation.Class.extend({
    selector: ".s_faq_collapse [data-toggle='collapse']",
    start: function () {
        this.$target.off("click._fix_apple_collapse").on("click._fix_apple_collapse", function () {});
    },
});

/* -------------------------------------------------------------------------
Gallery Animation

This ads a Modal window containing a slider when an image is clicked
inside a gallery
-------------------------------------------------------------------------*/
animation.registry.gallery = animation.Class.extend({
    selector: ".o_gallery:not(.o_slideshow)",
    start: function () {
        var self = this;
        this.$el.on("click", "img", this.click_handler);
    },
    click_handler : function (event) {
        var self = this;
        var $cur = $(event.currentTarget);
        var edition_mode = ($cur.closest("[contenteditable='true']").size() !== 0);

        // show it only if not in edition mode
        if (!edition_mode) {
            var urls = [],
                idx = undefined,
                milliseconds = undefined,
                params = undefined,
                $images = $cur.closest(".o_gallery").find("img"),
                size = 0.8,
                dimensions = {
                    min_width  : Math.round( window.innerWidth  *  size*0.9),
                    min_height : Math.round( window.innerHeight *  size),
                    max_width  : Math.round( window.innerWidth  *  size*0.9),
                    max_height : Math.round( window.innerHeight *  size),
                    width : Math.round( window.innerWidth *  size*0.9),
                    height : Math.round( window.innerHeight *  size)
            };

            $images.each(function () {
                urls.push($(this).attr("src"));
            });
            var $img = ($cur.is("img") === true) ? $cur : $cur.closest("img");
            idx = urls.indexOf($img.attr("src"));

            milliseconds = $cur.closest(".o_gallery").data("interval") || false;
            var params = {
                srcs : urls,
                index: idx,
                dim  : dimensions,
                interval : milliseconds,
                id: _.uniqueId("slideshow_")
            };
            var $modal = $(qweb.render('website.gallery.slideshow.lightbox', params));
            $modal.modal({
                keyboard : true,
                backdrop : true
            });
            $modal.on('hidden.bs.modal', function () {
                $(this).hide();
                $(this).siblings().filter(".modal-backdrop").remove(); // bootstrap leaves a modal-backdrop
                $(this).remove();

            });
            $modal.find(".modal-content, .modal-body.o_slideshow").css("height", "100%");
            $modal.appendTo(document.body);

            this.carousel = new animation.registry.gallery_slider($modal.find(".carousel").carousel());
        }
    } // click_handler
});

animation.registry.gallery_slider = animation.Class.extend({
    selector: ".o_slideshow",
    start: function () {
        var $carousel = this.$target.is(".carousel") ? this.$target : this.$target.find(".carousel");
        var self = this;
        var $indicator = $carousel.find('.carousel-indicators');
        var $lis = $indicator.find('li:not(.fa)');
        var $prev = $indicator.find('li.fa:first');
        var $next = $indicator.find('li.fa:last');
        var index = ($lis.filter('.active').index() || 1) -1;
        var page = Math.floor(index / 10);
        var nb = Math.ceil($lis.length / 10);

         // fix bootstrap use index insead of data-slide-to
        $carousel.on('slide.bs.carousel', function () {
            setTimeout(function () {
                var $item = $carousel.find('.carousel-inner .prev, .carousel-inner .next');
                var index = $item.index();
                $lis.removeClass("active")
                    .filter('[data-slide-to="'+index+'"]')
                    .addClass("active");
            },0);
        });

        function hide () {
            $lis.addClass('hidden').each(function (i) {
                if (i >= page*10 && i < (page+1)*10) {
                    $(this).removeClass('hidden');
                }
            });
            $prev.css('visibility', page === 0 ? 'hidden' : '');
            $next.css('visibility', (page+1) >= nb ? 'hidden' : '');
        }

        $indicator.find('li.fa').on('click', function () {
            page = (page + ($(this).hasClass('o_indicators_left')?-1:1)) % nb;
            $carousel.carousel(page*10);
            hide();
        });
        hide();

        $carousel.on('slid.bs.carousel', function () {
            var index = ($lis.filter('.active').index() || 1) -1;
            page = Math.floor(index / 10);
            hide();
        });
    }
});

});
