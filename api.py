"""Etimokart sunucu istemcisi (yalnızca standart kütüphane).

Kivy (Android/PC) ve Tkinter masaüstü sürümü aynı dosyayı kullanır.
Tüm çağrılar bloklayıcıdır: arayüzü dondurmamak için bir iş parçacığında (thread) çağır.
"""
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

# Raspberry Pi sunucunun herkese açık adresi (Cloudflare Tunnel). Ortam değişkeniyle de değiştirilebilir.
API_URL = os.environ.get("ETIMOKART_API", "https://api.etimokart.com.tr")


class ApiError(Exception):
    def __init__(self, msg, code="error", status=0):
        super().__init__(msg)
        self.msg, self.code, self.status = msg, code, status


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


class Client:
    def __init__(self, base=None, token=""):
        self.base = (base or API_URL).rstrip("/")
        self.token = token
        self._ctx = _ssl_context() if self.base.startswith("https") else None

    # --- düşük seviye ---
    def request(self, method, path, body=None, timeout=10):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ctx) as r:
                return json.loads(r.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read().decode("utf-8"))
                raise ApiError(j.get("error", "Sunucu hatası."), j.get("code", "error"), e.code)
            except (ValueError, UnicodeDecodeError, AttributeError):
                raise ApiError("Sunucu hatası.", "server_error", e.code)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise ApiError("Sunucuya bağlanılamadı. İnternetini kontrol et.", "network", 0)
        except ValueError:
            raise ApiError("Sunucudan geçersiz yanıt geldi.", "bad_response", 0)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body or {}, **kw)

    # --- hesap ---
    def register(self, username, password):
        r = self.post("/api/register", {"username": username, "password": password})
        self.token = r["token"]
        return r

    def login(self, username, password):
        r = self.post("/api/login", {"username": username, "password": password})
        self.token = r["token"]
        return r

    def logout(self):
        try:
            self.post("/api/logout")
        finally:
            self.token = ""

    def me(self):
        return self.get("/api/me")["user"]

    def delete_account(self, password):
        self.post("/api/delete_account", {"password": password})
        self.token = ""

    # --- oyun ---
    def game_start(self, level, lives=True):
        return self.post("/api/game/start", {"level": level, "lives": bool(lives)})

    def game_guess(self, game_id, guess):
        return self.post("/api/game/guess", {"game_id": game_id, "guess": guess})

    def game_hint(self, game_id):
        return self.post("/api/game/hint", {"game_id": game_id})

    def game_reveal(self, game_id):
        return self.post("/api/game/reveal", {"game_id": game_id})

    def game_finish(self, game_id):
        return self.post("/api/game/finish", {"game_id": game_id})["summary"]

    # --- liste / mağaza ---
    def leaderboard(self):
        return self.get("/api/leaderboard")

    def shop(self):
        return self.get("/api/shop")

    def shop_buy(self, item_id):
        return self.post("/api/shop/buy", {"item_id": item_id})

    def shop_equip(self, item_id):
        return self.post("/api/shop/equip", {"item_id": item_id})

    # --- arkadaşlar ---
    def friends(self):
        return self.get("/api/friends")

    def friend_request(self, username):
        return self.post("/api/friends/request", {"username": username})

    def friend_accept(self, username):
        return self.post("/api/friends/accept", {"username": username})

    def friend_decline(self, username):
        return self.post("/api/friends/decline", {"username": username})

    def friend_remove(self, username):
        return self.post("/api/friends/remove", {"username": username})

    # --- düello ---
    def duels(self):
        return self.get("/api/duels")

    def duel_invite(self, username, level):
        return self.post("/api/duel/invite", {"username": username, "level": level})

    def duel_accept(self, duel_id):
        return self.post("/api/duel/accept", {"duel_id": duel_id})

    def duel_decline(self, duel_id):
        return self.post("/api/duel/decline", {"duel_id": duel_id})

    def duel_cancel(self, duel_id):
        return self.post("/api/duel/cancel", {"duel_id": duel_id})

    def duel_state(self, duel_id):
        return self.get("/api/duel/state?duel_id=%d" % int(duel_id), timeout=6)

    def duel_guess(self, duel_id, guess):
        return self.post("/api/duel/guess", {"duel_id": duel_id, "guess": guess}, timeout=6)


# ----------------------------------------------------------------------
#  Küçük yerel ayar dosyası (oturum anahtarı, tema). Şifre ASLA saklanmaz.
# ----------------------------------------------------------------------
class Settings:
    def __init__(self, path):
        self.path = path
        self.d = {"token": "", "username": "", "dark_mode": True}
        try:
            with open(path, "r", encoding="utf-8") as f:
                j = json.load(f)
            if isinstance(j, dict):
                for k in self.d:
                    if k in j:
                        self.d[k] = j[k]
        except (OSError, ValueError):
            pass

    def get(self, k):
        return self.d.get(k)

    def set(self, **kw):
        self.d.update(kw)
        self.save()

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        except OSError:
            pass


def item_index(shop):
    """/api/shop yanıtından {ürün_id: ürün} sözlüğü."""
    idx = {}
    for cat in (shop or {}).get("categories", []):
        for it in cat["items"]:
            idx[it["id"]] = it
    return idx
