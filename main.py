"""Etimokart - Android (Kivy) arayüzü. Oyun/kayıt mantığı core.py'dedir."""
import colorsys
import os
import threading

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.utils import get_color_from_hex as hexc, platform

import time

import api
import core

Window.softinput_mode = "below_target"
if platform != "android":          # bilgisayarda telefon boyutunda aç
    Window.size = (420, 780)


# ----------------------------------------------------------------------
#  Küçük arayüz yardımcıları
# ----------------------------------------------------------------------
def app():
    return App.get_running_app()


def mix(hex_a, hex_b, t):
    a, b = hexc(hex_a), hexc(hex_b)
    return tuple(a[i] * (1 - t) + b[i] * t for i in range(3)) + (1,)


def palette(user):
    """Tema renkleri. Mağazadan arkaplan alınmışsa koyu tonlu temaya geçer."""
    tint = None
    if user:
        tint = app().item(user["active"].get("bg")).get("tint")
    if tint:
        return {"bg": hexc(tint), "card": mix(tint, "#ffffff", 0.10), "fg": hexc("#f1f5f9"),
                "sub": hexc("#b6c2d2"), "field": mix(tint, "#000000", 0.35)}
    if user and not app().settings.get("dark_mode"):
        return {"bg": hexc("#f1f5f9"), "card": hexc("#ffffff"), "fg": hexc("#0f172a"),
                "sub": hexc("#475569"), "field": hexc("#e2e8f0")}
    return {"bg": hexc("#0f172a"), "card": hexc("#1e293b"), "fg": hexc("#f1f5f9"),
            "sub": hexc("#94a3b8"), "field": hexc("#0b1220")}


def rainbow(hue):
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.8, 1.0)
    return (r, g, b, 1)


class Txt(Label):
    """Satır kaydıran, yüksekliği içeriğe uyan yazı."""

    def __init__(self, text="", size=16, color=None, bold=False, halign="center", **kw):
        super().__init__(text=text, font_size=sp(size), bold=bold, halign=halign, valign="middle",
                         color=color or app().pal["fg"], size_hint_y=None, **kw)
        self.bind(width=self._wrap, texture_size=self._fit)

    def _wrap(self, *_):
        self.text_size = (self.width, None)

    def _fit(self, *_):
        self.height = self.texture_size[1] + dp(6)


def Btn(text, cb, bg="#2980b9", fg="#ffffff", height=48, size=16, **kw):
    b = Button(text=text, background_normal="", background_down="", background_color=hexc(bg),
               color=hexc(fg), font_size=sp(size), size_hint_y=None, height=dp(height), **kw)
    b.bind(on_release=lambda *_: cb())
    return b


def Field(hint, password=False):
    p = app().pal
    return TextInput(hint_text=hint, multiline=False, password=password, write_tab=False,
                     size_hint_y=None, height=dp(48), font_size=sp(16), padding=[dp(12), dp(13)],
                     background_normal="", background_active="", background_color=p["field"],
                     foreground_color=p["fg"], hint_text_color=p["sub"], cursor_color=p["fg"])


class Card(BoxLayout):
    def __init__(self, color, border=None, **kw):
        super().__init__(orientation="vertical", size_hint_y=None, padding=dp(12), spacing=dp(8), **kw)
        self.bind(minimum_height=self.setter("height"))
        with self.canvas.before:
            Color(*color)
            self._rect = RoundedRectangle(radius=[dp(14)])
            self._bcol = Color(*(border or (0, 0, 0, 0)))
            self._line = Line(width=dp(2.5))
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._rect.pos, self._rect.size = self.pos, self.size
        self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(14))

    def set_border(self, rgba):
        self._bcol.rgba = rgba


class Swatch(Label):
    """Yuvarlak renk/avatar önizlemesi."""

    def __init__(self, rgba, letter="", d=44, **kw):
        super().__init__(text=letter, bold=True, font_size=sp(18), size_hint=(None, None),
                         size=(dp(d), dp(d)), color=(1, 1, 1, 1), **kw)
        with self.canvas.before:
            self._col = Color(*rgba)
            self._el = Ellipse()
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._el.pos, self._el.size = self.pos, self.size


def page(children):
    sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
    box = BoxLayout(orientation="vertical", size_hint_y=None, padding=[dp(16)] * 4, spacing=dp(10))
    box.bind(minimum_height=box.setter("height"))
    for c in children:
        box.add_widget(c)
    sv.add_widget(box)
    return sv


def tint_rgba(tint, fallback, hue=0.0):
    if tint == "rainbow":
        return rainbow(hue)
    return hexc(tint) if tint else fallback


# ----------------------------------------------------------------------
#  Ekranlar
# ----------------------------------------------------------------------
class Base(Screen):
    def on_pre_enter(self, *_):
        a = app()
        a.rainbow_cb = None
        Window.clearcolor = a.pal["bg"]
        self.clear_widgets()
        self.add_widget(self.build())

    def build(self):
        return BoxLayout()


def hexc_str(rgba):
    return "#%02x%02x%02x" % tuple(int(c * 255) for c in rgba[:3])


class AuthBase(Base):
    """Giriş/kayıt ortak davranışı: tekrar basılmayı engeller, hatayı formun içinde gösterir."""
    busy = False

    def set_busy(self, on, text=""):
        self.busy = on
        self.main_btn.disabled = on
        if on:
            self.err.text = ""
            self.err.color = app().pal["sub"]
            self.err.text = text
        else:
            self.err.color = hexc("#e74c3c")

    def fail(self, e):
        self.set_busy(False)
        self.err.text = e.msg if isinstance(e, api.ApiError) else "Beklenmeyen hata."
        self.pw.text = ""


class LoginScreen(AuthBase):
    def build(self):
        a, p = app(), app().pal
        self.u = Field("Kullanıcı adı")
        self.pw = Field("Şifre", password=True)
        self.u.text = a.settings.get("username") or ""
        self.u.bind(on_text_validate=lambda *_: setattr(self.pw, "focus", True))
        self.pw.bind(on_text_validate=lambda *_: self.go())
        self.err = Txt("", 14, hexc("#e74c3c"), bold=True)
        self.main_btn = Btn("Giriş Yap", self.go, "#27ae60")
        return page([
            Txt("ETİMOKART", 30, bold=True), Txt("Kelime evrimini keşfet, altınları topla!", 14, p["sub"]),
            self.u, self.pw, self.err, self.main_btn,
            Btn("Hesabın yok mu?  Kayıt Ol", lambda: a.goto("register"), "#00000000", "#5dade2", height=44, size=15),
        ])

    def go(self):
        if self.busy:
            return
        name, pw = self.u.text.strip(), self.pw.text
        if not name or not pw:
            self.err.text = "Kullanıcı adı ve şifreyi gir."
            return
        self.set_busy(True, "Giriş yapılıyor...")
        app().run(lambda: app().client.login(name, pw), lambda r: app().after_auth(r, False), self.fail)


class RegisterScreen(AuthBase):
    def build(self):
        a, p = app(), app().pal
        self.u = Field("Kullanıcı adı (2-20 karakter)")
        self.pw = Field("Şifre (en az 6 karakter)", password=True)
        self.pw2 = Field("Şifre (tekrar)", password=True)
        self.u.bind(on_text_validate=lambda *_: setattr(self.pw, "focus", True))
        self.pw.bind(on_text_validate=lambda *_: setattr(self.pw2, "focus", True))
        self.pw2.bind(on_text_validate=lambda *_: self.go())
        self.err = Txt("", 14, hexc("#e74c3c"), bold=True)
        self.main_btn = Btn("Kayıt Ol", self.go, "#2980b9")
        return page([
            Txt("KAYIT OL", 30, bold=True), Txt("Yeni hesap oluştur, 50 Altın hediye kazan!", 14, p["sub"]),
            self.u, self.pw, self.pw2, self.err, self.main_btn,
            Btn("← Girişe dön", lambda: a.goto("login"), "#00000000", "#5dade2", height=44, size=15),
        ])

    def go(self):
        if self.busy:
            return
        name, pw = " ".join(self.u.text.split()), self.pw.text
        if len(name) < 2:
            self.err.text = "Kullanıcı adı en az 2 karakter olmalı."
        elif len(pw) < 6:
            self.err.text = "Şifre en az 6 karakter olmalı."
        elif pw != self.pw2.text:
            self.err.text = "Şifreler birbiriyle aynı değil."
        else:
            self.set_busy(True, "Hesap oluşturuluyor...")
            app().run(lambda: app().client.register(name, pw), lambda r: app().after_auth(r, True), self.fail)


class MainScreen(Base):
    def build(self):
        a, p, u = app(), app().pal, app().user
        av = a.item(u["active"].get("avatar"))
        head = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
        head.add_widget(Swatch(tint_rgba(av.get("tint"), hexc("#7f8c8d")), u["username"][:1].upper()))
        head.add_widget(Txt(f"{u['username']}   |   Altın: {u['gold']}   |   Rekor: {u['best_score']}", 14, halign="left"))

        nxt = u.get("next_title")
        nxt_txt = f"Sonraki ünvan: {nxt['name']} ({nxt['need'] - u['total_score']} puan kaldı)" if nxt else "En yüksek ünvandasın!"
        stats = Card(p["card"])
        stats.add_widget(Txt(f"Toplam Puan: {u['total_score']}", 20, hexc("#f39c12"), bold=True))
        stats.add_widget(Txt(f"Ünvan: {u['title']}", 14))
        stats.add_widget(Txt(nxt_txt, 12, p["sub"]))
        stats.add_widget(Txt(f"Sıralama: #{u['rank']} / {u['total_players']}", 14, hexc("#5dade2"), bold=True))
        stats.add_widget(Txt(f"Düello: {u['wins']} galibiyet - {u['losses']} yenilgi - {u['draws']} beraberlik", 12, p["sub"]))

        badge = u.get("pending_friend_requests", 0) + u.get("pending_duel_invites", 0)
        items = [head]
        if a.flash:
            items.append(Txt(a.flash, 14, hexc("#27ae60"), bold=True))
            a.flash = ""
        items += [
            stats,
            Btn("Oyuna Başla", lambda: a.goto("difficulty"), "#2196F3"),
            Btn("Arkadaşlar & Düello" + (f"  ({badge} yeni)" if badge else ""), lambda: a.goto("friends"), "#d35400"),
            Btn("Mağaza (Kozmetikler)", lambda: a.open_shop(), "#8e44ad"),
            Btn("Lider Tablosu (İlk 100)", lambda: a.goto("board"), "#16a085"),
            Btn("Koyu / Açık Tema", a.toggle_theme, "#546e7a"),
            Btn("Çıkış Yap", a.logout, "#c0392b"),
            Btn("Hesabı Sil", a.ask_delete, "#7b241c", height=42, size=14),
        ]
        return page(items)


class DifficultyScreen(Base):
    def build(self):
        a, p = app(), app().pal
        rows = [Txt("Zorluk Seviyesi", 26, bold=True), Txt("Kelime havuzunun tarihsel derinliğine göre seç.", 13, p["sub"])]
        for key, label, color in core.LEVELS:
            rows.append(Btn(f"{label}  ({core.LEVEL_INFO[key]})", lambda k=key: a.pick_level(k), color, height=60))
        rows.append(Btn("← Geri", a.go_main, "#546e7a"))
        return page(rows)


class LivesScreen(Base):
    def build(self):
        a, p = app(), app().pal
        self.err = Txt("", 14, hexc("#e74c3c"), bold=True)
        return page([
            Txt("Canlar Aktif Olsun mu?", 26, bold=True),
            Txt(f"{a.level.capitalize()} seviye", 14, p["sub"]),
            Btn("Evet (canlı oyna)", lambda: a.start_game(True, self), "#27ae60", height=56),
            Btn("Hayır (sınırsız deneme)", lambda: a.start_game(False, self), "#546e7a", height=56),
            self.err,
            Btn("← Geri", lambda: a.goto("difficulty"), "#546e7a"),
        ])


class GameScreen(Base):
    """Kelime başına bir kez kurulur; geri bildirim yerinde güncellenir (klavye kapanmasın)."""

    def build(self):
        a, p, g, u = app(), app().pal, app().game, app().user
        self.locked = self.busy = False
        frame, ws, fx = (a.item(u["active"].get(k)) for k in ("frame", "wstyle", "fx"))
        self.fx_color = tint_rgba(fx.get("tint"), hexc("#27ae60"))

        self.info = Txt("", 13, p["sub"], halign="left")
        self.lives = Txt("", 14, hexc("#e74c3c"), bold=True, halign="right")
        top = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        top.add_widget(Btn("Bitir", a.finish_game, "#e74c3c", height=40, size=14, size_hint_x=None, width=dp(80)))
        top.add_widget(self.info)
        top.add_widget(self.lives)
        self.score = Txt("", 15, hexc("#f39c12"), bold=True)

        self.card = Card(p["card"], border=tint_rgba(frame["tint"], None) if frame.get("tint") else None)
        self.card.add_widget(Txt(f"ID: #{g['word']['id']}", 12, p["sub"]))
        self.card.add_widget(Txt("Kelimenin evrim sürecini incele ve son halini tahmin et:", 14, p["sub"]))
        self.word = Txt("", 24, tint_rgba(ws.get("tint"), p["fg"]), bold=True, italic=bool(ws.get("italic")))
        self.card.add_widget(self.word)
        self.fb = Txt("", 15, hexc("#e74c3c"), bold=True)
        self.card.add_widget(self.fb)

        rb_frame, rb_word = frame.get("tint") == "rainbow", ws.get("tint") == "rainbow"
        if rb_frame or rb_word:
            def cb(color):
                if rb_frame:
                    self.card.set_border(color)
                if rb_word:
                    self.word.color = color
            a.rainbow_cb = cb

        self.guess = Field("Tahmininizi yazın...")
        self.guess.halign = "center"
        self.guess.bind(on_text_validate=lambda *_: self.submit())
        self.ok_btn = Btn(f"Tahmin Et (+{core.POINTS_CORRECT} Puan)", self.submit, "#2980b9")
        self.hint_btn = Btn(f"İpucu Al (-{core.POINTS_HINT} Puan)", self.hint, "#f39c12", height=44, size=14)
        self.show_btn = Btn(f"Cevabı Göster (-{core.POINTS_REVEAL} Puan)", self.reveal_ask, "#e67e22", height=44, size=14)

        self.refresh()
        items = [top, self.score, self.card, self.guess, self.ok_btn]
        if g["word"]["can_hint"]:
            items.append(self.hint_btn)
        items.append(self.show_btn)
        sv = page(items)
        Clock.schedule_once(lambda dt: setattr(self.guess, "focus", True), 0.2)
        return sv

    def refresh(self):
        g = app().game
        self.info.text = f"Seviye: {g['level'].upper()} | Kalan: {g['word']['remaining']}"
        self.lives.text = f"Can: {g['lives']}" if g["lives_enabled"] else "Can: Sınırsız"
        self.score.text = f"Puan: {g['score']}     Altın: +{g['gold']}"
        self.word.text = "  →  ".join(g["word"]["shown"]) + "  →  ?"

    def say(self, text, color):
        self.fb.text, self.fb.color = text, color

    def lock(self):
        self.locked = True
        for w in (self.guess, self.ok_btn, self.hint_btn, self.show_btn):
            w.disabled = True

    def _fail(self, e):
        self.busy = False
        if isinstance(e, api.ApiError) and e.code == "too_fast":
            self.say("Çok hızlı! Biraz bekle.", hexc("#f39c12"))
        else:
            self.say(e.msg if isinstance(e, api.ApiError) else "Hata oluştu.", hexc("#e74c3c"))

    def _send(self, call, on_ok):
        if self.locked or self.busy:
            return
        self.busy = True

        def ok(r):
            self.busy = False
            on_ok(r)
        app().run(call, ok, self._fail)

    def _sync(self, r):
        g = app().game
        for k in ("score", "lives"):
            if k in r:
                g[k] = r[k]

    def submit(self):
        a, g = app(), app().game
        text = self.guess.text.strip()
        if not text:
            return

        def on_ok(r):
            self._sync(r)
            if r["result"] == "correct":
                g["gold"] += r["gold"]
                self.refresh()
                gold = f", +{r['gold']} Altın" if r["gold"] else ""
                self.say(f"Harika! +{core.POINTS_CORRECT} Puan{gold}", self.fx_color)
                self.lock()
                nxt = (lambda dt: a.show_summary(r["summary"])) if r["finished"] else (lambda dt: a.next_word(r["word"]))
                Clock.schedule_once(nxt, 1.1)
            elif r["result"] == "gameover":
                a.show_summary(r["summary"])
            elif r["result"] == "wrong":
                self.refresh()
                pen = f"(-{r['penalty']} Puan)" if r["penalty"] else "(puan kaybı yok)"
                self.say(f"Yanlış tahmin! {pen}", hexc("#e74c3c"))
                self.guess.text = ""
                self.guess.focus = True
        self._send(lambda: a.client.game_guess(g["game_id"], text), on_ok)

    def hint(self):
        a, g = app(), app().game

        def on_ok(r):
            g["score"], g["word"] = r["score"], r["word"]
            self.refresh()
            self.say(f"İpucu kullanıldı (-{core.POINTS_HINT} Puan)", hexc("#f39c12"))
            if self.hint_btn.parent:
                self.hint_btn.parent.remove_widget(self.hint_btn)
        self._send(lambda: a.client.game_hint(g["game_id"]), on_ok)

    def reveal_ask(self):
        if self.locked:
            return
        app().confirm("Cevabı Göster", f"Cevabı görmek {core.POINTS_REVEAL} puan ve 1 can götürür. Emin misin?",
                      "Evet", self.reveal)

    def reveal(self):
        a, g = app(), app().game

        def on_ok(r):
            self._sync(r)
            if r["result"] == "gameover":
                a.show_summary(r["summary"])
                return
            self.refresh()
            self.say(f"Doğru cevap: {r['answer']} (-{core.POINTS_REVEAL} Puan)", hexc("#e67e22"))
            self.lock()
            nxt = (lambda dt: a.show_summary(r["summary"])) if r["finished"] else (lambda dt: a.next_word(r["word"]))
            Clock.schedule_once(nxt, 1.8)
        self._send(lambda: a.client.game_reveal(g["game_id"]), on_ok)


class SummaryScreen(Base):
    def build(self):
        a, p, s = app(), app().pal, app().summary
        items = [Txt("OYUN SONU ÖZETİ", 24, hexc("#f39c12"), bold=True), Txt(s.get("reason", ""), 14, p["sub"])]
        card = Card(p["card"])
        for line in (f"Oyun Puanı: {s['score']} Puan", f"Kazanılan Altın: +{s['gold']}",
                     f"Doğru: {s['correct']}   |   Yanlış: {s['wrong']}",
                     f"En Yüksek Rekorun: {s['best']} Puan", f"Toplam Puan: {s['total']}"):
            card.add_widget(Txt(line, 16, bold=True))
        items.append(card)
        if s.get("record"):
            items.append(Txt("YENİ KİŞİSEL REKOR!", 16, hexc("#27ae60"), bold=True))
        if s.get("rank_up"):
            items.append(Txt(f"Yeni ünvan: {s['rank_up']}!", 16, hexc("#8e44ad"), bold=True))
        items += [Btn("Tekrar Oyna", lambda: a.goto("difficulty"), "#2196F3"),
                  Btn("Ana Menü", a.go_main, "#546e7a")]
        return page(items)


class ShopScreen(Base):
    def build(self):
        a, p, u = app(), app().pal, app().user
        cats = a.shop["categories"]
        cat = cats[a.shop_cat]
        tabs = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(4))
        for i, c in enumerate(cats):
            tabs.add_widget(Btn(c["title"], lambda i=i: a.set_shop_cat(i), "#8e44ad" if i == a.shop_cat else "#546e7a",
                                height=40, size=12))
        items = [Txt("Mağaza", 26, bold=True), Txt(f"Altının: {a.shop['gold']}", 16, hexc("#f39c12"), bold=True), tabs]
        if a.shop_msg:
            items.append(Txt(a.shop_msg, 13, hexc("#27ae60") if a.shop_ok else hexc("#e74c3c"), bold=True))
        for it in cat["items"]:
            if it["active"]:
                label, color = "Kullanılıyor", "#27ae60"
            elif it["owned"]:
                label, color = "Kullan", "#2980b9"
            else:
                label, color = f"Satın Al ({it['price']})", "#e67e22"
            row = Card(p["card"])
            top = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
            top.add_widget(Swatch(tint_rgba(it.get("tint"), hexc("#7f8c8d")), "", 40))
            col = BoxLayout(orientation="vertical")
            col.add_widget(Label(text=it["name"], bold=True, font_size=sp(15), color=p["fg"], halign="left",
                                 text_size=(dp(200), None)))
            col.add_widget(Label(text=it["desc"], font_size=sp(12), color=p["sub"], halign="left",
                                 text_size=(dp(200), None)))
            top.add_widget(col)
            row.add_widget(top)
            row.add_widget(Btn(label, lambda it=it: a.shop_buy(it), color, height=40, size=14))
            items.append(row)
        items.append(Btn("← Geri", a.go_main, "#546e7a"))
        return page(items)


class BoardScreen(Base):
    def build(self):
        a, p = app(), app().pal
        self.status = Txt("Yükleniyor...", 14, p["sub"])
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
        self.box.bind(minimum_height=self.box.setter("height"))
        a.run(a.client.leaderboard, self._show, lambda e: self._show(None))
        return page([Txt("Lider Tablosu", 26, bold=True), self.status, self.box,
                     Btn("← Geri", a.go_main, "#546e7a")])

    def _show(self, rows):
        p = app().pal
        if rows is None:
            self.status.text = "Tablo yüklenemedi. İnternetini kontrol et."
            return
        self.status.text = f"En iyi {len(rows)} oyuncu" if rows else "Henüz tabloda kimse yok."
        me = app().user["username"]
        for i, r in enumerate(rows):
            line = Card(p["card"], border=hexc("#f39c12") if r["username"] == me else None)
            line.add_widget(Txt(f"{i + 1}.  {r['username']}  -  {r['total_score']} puan", 15, halign="left", bold=i < 3))
            self.box.add_widget(line)


class FriendsScreen(Base):
    """Arkadaş listesi, istekler, düello davetleri. Açıkken 3 sn'de bir kendini yeniler."""

    def build(self):
        a, p = app(), app().pal
        self.sig = None
        self.add = Field("Arkadaş eklemek için kullanıcı adı")
        self.add.bind(on_text_validate=lambda *_: self.send())
        self.msg = Txt(a.friend_msg, 13, hexc("#27ae60"), bold=True)
        a.friend_msg = ""
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.box.bind(minimum_height=self.box.setter("height"))
        self.poll_ev = Clock.schedule_interval(lambda dt: self.load(), 3)
        self.load()
        return page([Txt("Arkadaşlar & Düello", 24, bold=True), self.add,
                     Btn("Arkadaş Ekle", self.send, "#2980b9", height=44), self.msg, self.box,
                     Btn("← Geri", a.go_main, "#546e7a")])

    def on_leave(self, *_):
        ev = getattr(self, "poll_ev", None)
        if ev:
            ev.cancel()
            self.poll_ev = None

    def say(self, text, ok=True):
        self.msg.text, self.msg.color = text, hexc("#27ae60") if ok else hexc("#e74c3c")

    def act(self, fn, *args):
        app().run(lambda: fn(*args), lambda r: (self.say(r.get("message", "Tamam.")), self.load(True)),
                  lambda e: self.say(e.msg, False))

    def send(self):
        name = self.add.text.strip()
        if name:
            self.add.text = ""
            self.act(app().client.friend_request, name)

    def load(self, force=False):
        a = app()
        if self.sm_current() != "friends":
            return

        def work():
            return a.client.friends(), a.client.duels()
        a.run(work, lambda r: self.fill(r, force), lambda e: None)

    def sm_current(self):
        return app().sm.current

    def fill(self, res, force):
        a, p = app(), app().pal
        fr, du = res
        sig = repr((fr, [(d["id"], d["level"]) for d in du["incoming"]], du["active"], du["history"]))
        if sig == self.sig and not force:
            return
        self.sig = sig
        self.box.clear_widgets()
        c = a.client

        def head(t):
            self.box.add_widget(Txt(t, 16, hexc("#f39c12"), bold=True, halign="left"))

        if du["active"]:
            self.box.add_widget(Btn("Devam eden düelloya dön", lambda: a.open_duel(du["active"]), "#d35400"))
        if du["incoming"]:
            head("Düello davetleri")
            for d in du["incoming"]:
                row = Card(p["card"])
                row.add_widget(Txt(f"{d['from']} seni {d['level'].upper()} düelloya çağırıyor!", 14))
                b = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
                b.add_widget(Btn("Kabul", lambda d=d: a.accept_duel(d["id"]), "#27ae60", height=40, size=14))
                b.add_widget(Btn("Reddet", lambda d=d: self.act(c.duel_decline, d["id"]), "#c0392b", height=40, size=14))
                row.add_widget(b)
                self.box.add_widget(row)
        if fr["incoming"]:
            head("Arkadaşlık istekleri")
            for f in fr["incoming"]:
                row = Card(p["card"])
                row.add_widget(Txt(f"{f['username']} ({f['title']})", 14))
                b = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
                b.add_widget(Btn("Kabul", lambda f=f: self.act(c.friend_accept, f["username"]), "#27ae60", height=40, size=14))
                b.add_widget(Btn("Reddet", lambda f=f: self.act(c.friend_decline, f["username"]), "#c0392b", height=40, size=14))
                row.add_widget(b)
                self.box.add_widget(row)
        head(f"Arkadaşların ({len(fr['friends'])})")
        if not fr["friends"]:
            self.box.add_widget(Txt("Henüz arkadaşın yok. Yukarıdan kullanıcı adı yazarak ekle.", 13, p["sub"]))
        for f in fr["friends"]:
            row = Card(p["card"])
            dot = "●" if f["online"] else "○"
            row.add_widget(Txt(f"{dot} {f['username']}  -  {f['total_score']} puan  ({f['title']})", 14, halign="left"))
            b = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
            b.add_widget(Btn("Düello", lambda f=f: a.pick_duel_level(f["username"]), "#d35400", height=40, size=14))
            b.add_widget(Btn("Çıkar", lambda f=f: a.confirm("Arkadaşı çıkar", f"{f['username']} arkadaş listenden çıkarılsın mı?",
                                                           "Çıkar", lambda: self.act(c.friend_remove, f["username"])),
                             "#78909c", height=40, size=14))
            row.add_widget(b)
            self.box.add_widget(row)
        if fr["outgoing"]:
            head("Gönderilen istekler")
            for f in fr["outgoing"]:
                self.box.add_widget(Txt(f"{f['username']} (yanıt bekleniyor)", 13, p["sub"], halign="left"))
        if du["history"]:
            head("Son düellolar")
            names = {"win": "Galibiyet", "lose": "Yenilgi", "draw": "Beraberlik"}
            for h in du["history"]:
                self.box.add_widget(Txt(f"{names[h['result']]} - {h['opponent']}  {h['my_score']}-{h['opp_score']}  ({h['level']})",
                                        13, p["sub"], halign="left"))


class DuelScreen(Base):
    """Canlı düello: ~0.8 sn'de bir sunucuyu yoklar, her şeyi sunucudan okur."""

    def build(self):
        a, p, u = app(), app().pal, app().user
        self.view, self.recv, self.busy_poll, self.sent_round = None, 0.0, False, None
        self.closed = False
        self.head = Txt("Düello", 22, bold=True)
        self.score = Txt("", 18, hexc("#f39c12"), bold=True)
        self.timer = Txt("", 28, hexc("#e74c3c"), bold=True)
        self.card = Card(p["card"])
        self.word = Txt("", 24, bold=True)
        self.card.add_widget(self.word)
        self.fb = Txt("", 15, hexc("#e74c3c"), bold=True)
        self.guess = Field("Tahminini yaz...")
        self.guess.halign = "center"
        self.guess.bind(on_text_validate=lambda *_: self.submit())
        self.ok_btn = Btn("Tahmin Et", self.submit, "#2980b9")
        self.leave_btn = Btn("Düellodan Çekil", self.leave, "#c0392b", height=42, size=14)
        self.done_btn = Btn("Arkadaşlara Dön", lambda: a.goto("friends"), "#546e7a")
        self.done_btn.opacity, self.done_btn.disabled = 0, True
        self.poll_ev = Clock.schedule_interval(lambda dt: self.poll(), 0.8)
        self.tick_ev = Clock.schedule_interval(lambda dt: self.tick(), 0.1)
        self.poll()
        return page([self.head, self.score, self.timer, self.card, self.fb, self.guess, self.ok_btn,
                     self.leave_btn, self.done_btn])

    def on_leave(self, *_):
        self.closed = True
        for n in ("poll_ev", "tick_ev"):
            ev = getattr(self, n, None)
            if ev:
                ev.cancel()
                setattr(self, n, None)

    def poll(self):
        if self.busy_poll or self.closed:
            return
        self.busy_poll = True
        a = app()

        def done():
            self.busy_poll = False
        a.run(lambda: a.client.duel_state(a.duel_id), lambda r: (done(), self.apply(r)),
              lambda e: (done(), self.fb.__setattr__("text", e.msg)))

    def apply(self, v):
        if self.closed:
            return
        self.view, self.recv = v, time.time()
        self.score.text = f"{v['me']}  {v['my_score']}  -  {v['opp_score']}  {v['opponent']}"
        ph = v["phase"]
        self.head.text = f"Düello  ({v['level'].upper()})  Tur {min(v['round'], v['total'])}/{v['total']}"
        if ph == "round":
            self.word.text = "  →  ".join(v["word"]["shown"]) + "  →  ?"
            if self.sent_round != v["round"]:
                self.sent_round = v["round"]
                self.fb.text = ""
                self.guess.text = ""
                self.guess.focus = True
        elif ph == "between":
            last = v["last"]
            who = {"me": "Sen bildin!", "opp": f"{v['opponent']} bildi.", None: "Süre doldu."}[last["winner"]]
            self.word.text = f"Cevap: {last['answer']}"
            self.fb.text, self.fb.color = who, hexc("#27ae60") if last["winner"] == "me" else hexc("#e67e22")
        elif ph == "countdown":
            self.word.text = "Hazır ol..."
        elif ph == "pending":
            self.word.text = ("Davet gönderildi, " + v["opponent"] + " bekleniyor..." if v["invited_by_me"]
                              else "Düello başlıyor...")
        else:
            res = v.get("result")
            msgs = {"win": "KAZANDIN!", "lose": "Kaybettin.", "draw": "Berabere!"}
            text = {"declined": "Davet reddedildi.", "expired": "Davetin süresi doldu.",
                    "cancelled": "Davet iptal edildi."}.get(ph) or msgs.get(res, "Düello bitti.")
            if ph == "finished":
                text += f"   (+{v.get('gold', 0)} Altın)"
            self.word.text = text
            self.finish()

    def finish(self):
        self.closed = True
        self.timer.text = ""
        self.guess.disabled = self.ok_btn.disabled = True
        self.leave_btn.opacity, self.leave_btn.disabled = 0, True
        self.done_btn.opacity, self.done_btn.disabled = 1, False
        for n in ("poll_ev", "tick_ev"):
            ev = getattr(self, n, None)
            if ev:
                ev.cancel()
                setattr(self, n, None)
        app().refresh_user()

    def tick(self):
        v = self.view
        if not v:
            return
        el = time.time() - self.recv
        ph = v["phase"]
        if ph == "round":
            self.timer.text = f"{max(0.0, v['time_left'] - el):.0f} sn"
        elif ph == "countdown":
            self.timer.text = f"{max(0.0, v['starts_in'] - el):.0f}"
        elif ph == "between":
            self.timer.text = ""
        elif ph == "pending":
            self.timer.text = ""

    def submit(self):
        v, a = self.view, app()
        if not v or v["phase"] != "round":
            return
        text = self.guess.text.strip()
        if not text:
            return
        self.guess.text = ""

        def ok(r):
            res = r["result"]
            if res == "correct":
                self.fb.text, self.fb.color = "Doğru!", hexc("#27ae60")
            elif res in ("wrong", "locked"):
                self.fb.text, self.fb.color = "Yanlış! Kısa süre bekle.", hexc("#e74c3c")
            elif res == "late":
                self.fb.text, self.fb.color = "Tur bitti.", hexc("#e67e22")
            self.poll()
        a.run(lambda: a.client.duel_guess(a.duel_id, text), ok,
              lambda e: self.fb.__setattr__("text", e.msg))

    def leave(self):
        a, v = app(), self.view
        txt = "Düellodan çekilirsen yenilmiş sayılırsın. Emin misin?" if v and v["phase"] != "pending" else "Davet iptal edilsin mi?"
        a.confirm("Düello", txt, "Evet", lambda: a.run(lambda: a.client.duel_cancel(a.duel_id),
                                                        lambda r: self.poll(), lambda e: self.poll()))


# ----------------------------------------------------------------------
#  Uygulama
# ----------------------------------------------------------------------
class EtimokartApp(App):
    title = "Etimokart"

    def build(self):
        self.settings = api.Settings(os.path.join(self.user_data_dir, "etimokart_ayar.json"))
        self.client = api.Client(token=self.settings.get("token") or "")
        self.user, self.shop, self.catalog = None, None, {}
        self.pal = palette(None)
        self.level, self.game, self.summary = "kolay", None, {}
        self.flash, self.shop_msg, self.shop_ok, self.shop_cat = "", "", True, 0
        self.friend_msg, self.duel_id = "", None
        self.rainbow_cb, self._hue = None, 0.0

        self.sm = ScreenManager(transition=NoTransition())
        for name, cls in (("login", LoginScreen), ("register", RegisterScreen), ("main", MainScreen),
                          ("difficulty", DifficultyScreen), ("lives", LivesScreen), ("game", GameScreen),
                          ("summary", SummaryScreen), ("shop", ShopScreen), ("board", BoardScreen),
                          ("friends", FriendsScreen), ("duel", DuelScreen)):
            self.sm.add_widget(cls(name=name))

        Window.bind(on_keyboard=self.on_key)
        Clock.schedule_interval(self._tick, 0.08)

        if self.client.token:                       # kayıtlı oturum varsa sessizce devam et
            self.sm.current = "login"
            self.run(self._load_all, lambda r: self.enter(*r),
                     lambda e: self.sm.get_screen("login").err.__setattr__("text", "") if e.code != "network"
                     else self.sm.get_screen("login").err.__setattr__("text", e.msg))
        else:
            self.sm.current = "login"
        return self.sm

    # --- iş parçacığı yardımcıları ---
    def run(self, fn, ok=None, err=None):
        """fn'yi arka planda çalıştırır; sonucu ana iş parçacığında ok(sonuç) / err(hata) ile verir."""
        def work():
            try:
                res = fn()
            except api.ApiError as e:
                if e.code == "unauthorized" and self.user:
                    Clock.schedule_once(lambda dt: self.session_expired(), 0)
                    return
                if err:
                    Clock.schedule_once(lambda dt, e=e: err(e), 0)
                return
            except Exception as e:                   # beklenmeyen hata uygulamayı düşürmesin
                ex = api.ApiError("Beklenmeyen hata: %s" % type(e).__name__)
                if err:
                    Clock.schedule_once(lambda dt: err(ex), 0)
                return
            if ok:
                Clock.schedule_once(lambda dt: ok(res), 0)
        threading.Thread(target=work, daemon=True).start()

    def session_expired(self):
        self.clear_session()
        self.goto("login")

    def _load_all(self):
        return self.client.me(), self.client.shop()

    def item(self, item_id):
        return self.catalog.get(item_id) or {"tint": None}

    # --- genel ---
    def goto(self, name):
        if self.sm.current == name:
            self.sm.get_screen(name).on_pre_enter()
        self.sm.current = name

    def theme(self):
        self.pal = palette(self.user)
        Window.clearcolor = self.pal["bg"]

    def toggle_theme(self):
        self.settings.set(dark_mode=not self.settings.get("dark_mode"))
        self.theme()
        self.goto("main")

    def _tick(self, dt):
        self._hue = (self._hue + 0.01) % 1.0
        if self.rainbow_cb:
            self.rainbow_cb(rainbow(self._hue))

    def on_key(self, window, key, *args):
        if key != 27:                      # Android geri tuşu
            return False
        cur = self.sm.current
        if cur == "game":
            self.finish_game()
        elif cur == "duel":
            self.goto("friends")
        elif cur in ("difficulty", "lives", "shop", "board", "summary", "friends"):
            self.go_main()
        elif cur == "register":
            self.goto("login")
        else:
            return False
        return True

    # --- hesap ---
    def after_auth(self, res, fresh):
        self.settings.set(token=res["token"], username=res["user"]["username"])
        if fresh:
            self.flash = f"Kayıt başarılı, hoş geldin {res['user']['username']}! Hediye 50 Altın hesabına yüklendi."
        self.run(self.client.shop, lambda s: self.enter(res["user"], s),
                 lambda e: self._auth_err(e))

    def _auth_err(self, e):
        scr = self.sm.current_screen
        if hasattr(scr, "fail"):
            scr.fail(e)

    def enter(self, user, shop):
        self.user, self.shop = user, shop
        self.catalog = api.item_index(shop)
        self.theme()
        self.goto("main")

    def refresh_user(self):
        """Sessizce kullanıcı bilgisini (puan, altın, rozetler) yeniler."""
        def ok(u):
            self.user = u
        self.run(self.client.me, ok)

    def go_main(self):
        def ok(u):
            self.user = u
            self.theme()
            self.goto("main")
        self.run(self.client.me, ok, lambda e: self.goto("main"))

    def clear_session(self):
        self.settings.set(token="")
        self.client.token = ""
        self.user = None
        self.pal = palette(None)
        Window.clearcolor = self.pal["bg"]

    def logout(self):
        old = api.Client(self.client.base, self.client.token)
        threading.Thread(target=lambda: self._quiet(old.post, "/api/logout"), daemon=True).start()
        self.clear_session()
        self.goto("login")

    @staticmethod
    def _quiet(fn, *a):
        try:
            fn(*a)
        except Exception:
            pass

    def ask_delete(self):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        box.add_widget(Txt(f"'{self.user['username']}' hesabı KALICI olarak silinecek. Onaylamak için şifreni gir:", 14))
        pw = Field("Şifre", password=True)
        err = Txt("", 13, hexc("#e74c3c"), bold=True)
        box.add_widget(pw)
        box.add_widget(err)
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        pop = Popup(title="Hesabı Sil", content=box, size_hint=(0.9, None), height=dp(330))

        def do():
            def ok(_):
                pop.dismiss()
                self.clear_session()
                self.goto("login")
            def bad(e):
                err.text, pw.text = e.msg, ""
            self.run(lambda: self.client.delete_account(pw.text), ok, bad)

        row.add_widget(Btn("Vazgeç", pop.dismiss, "#78909c"))
        row.add_widget(Btn("Sil", do, "#c0392b"))
        box.add_widget(row)
        pop.open()

    def confirm(self, title, text, yes_text, on_yes):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        box.add_widget(Txt(text, 15))
        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        pop = Popup(title=title, content=box, size_hint=(0.88, None), height=dp(240))
        row.add_widget(Btn("Vazgeç", pop.dismiss, "#78909c"))
        row.add_widget(Btn(yes_text, lambda: (pop.dismiss(), on_yes()), "#c0392b"))
        box.add_widget(row)
        pop.open()

    def notice(self, text):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
        box.add_widget(Txt(text, 15))
        pop = Popup(title="Etimokart", content=box, size_hint=(0.88, None), height=dp(220))
        box.add_widget(Btn("Tamam", pop.dismiss, "#2980b9"))
        pop.open()

    # --- oyun ---
    def pick_level(self, level):
        self.level = level
        self.goto("lives")

    def start_game(self, lives_enabled, screen):
        screen.err.text = "Oyun hazırlanıyor..."

        def ok(g):
            self.game = g
            self.goto("game")
        self.run(lambda: self.client.game_start(self.level, lives_enabled), ok,
                 lambda e: setattr(screen.err, "text", e.msg))

    def next_word(self, word):
        if self.sm.current != "game" or not self.game:
            return                        # bu arada ekrandan çıkıldıysa
        self.game["word"] = word
        self.goto("game")

    def show_summary(self, s):
        self.summary = s
        self.refresh_user()
        self.goto("summary")

    def finish_game(self):
        if not self.game:
            return self.go_main()
        self.run(lambda: self.client.game_finish(self.game["game_id"]), self.show_summary,
                 lambda e: self.notice(e.msg))

    # --- mağaza ---
    def open_shop(self):
        def ok(s):
            self.shop, self.catalog = s, api.item_index(s)
            self.shop_msg = ""
            self.goto("shop")
        self.run(self.client.shop, ok, lambda e: self.notice(e.msg))

    def set_shop_cat(self, i):
        self.shop_cat, self.shop_msg = i, ""
        self.goto("shop")

    def shop_buy(self, item):
        call = self.client.shop_equip if item["owned"] else self.client.shop_buy

        def ok(r):
            self.user = r["user"]
            self.shop_msg, self.shop_ok = r["message"], True
            self.theme()
            self.open_shop_keep(r["message"])

        def bad(e):
            self.shop_msg, self.shop_ok = e.msg, False
            self.goto("shop")
        self.run(lambda: call(item["id"]), ok, bad)

    def open_shop_keep(self, msg):
        def ok(s):
            self.shop, self.catalog = s, api.item_index(s)
            self.shop_msg, self.shop_ok = msg, True
            self.goto("shop")
        self.run(self.client.shop, ok, lambda e: self.notice(e.msg))

    # --- düello ---
    def pick_duel_level(self, friend):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        pop = Popup(title=f"{friend} ile düello", content=box, size_hint=(0.88, None), height=dp(330))
        box.add_widget(Txt("Seviye seç (10 tur, her tur 20 sn):", 14))
        for key, label, color in core.LEVELS:
            box.add_widget(Btn(label, lambda k=key: (pop.dismiss(), self.invite(friend, k)), color, height=44))
        box.add_widget(Btn("Vazgeç", pop.dismiss, "#78909c", height=40))
        pop.open()

    def invite(self, friend, level):
        def ok(r):
            self.duel_id = r["duel_id"]
            self.goto("duel")
        self.run(lambda: self.client.duel_invite(friend, level), ok, lambda e: self.notice(e.msg))

    def accept_duel(self, duel_id):
        def ok(r):
            self.duel_id = r["duel_id"]
            self.goto("duel")
        self.run(lambda: self.client.duel_accept(duel_id), ok, lambda e: self.notice(e.msg))

    def open_duel(self, duel_id):
        self.duel_id = duel_id
        self.goto("duel")


if __name__ == "__main__":
    EtimokartApp().run()
