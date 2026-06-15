# deploy/ — WAHA NOWEB store auto-heal

Workaround for [devlikeapro/waha#868](https://github.com/devlikeapro/waha/issues/868):
on the WAHA **CORE** tier the per-session NOWEB store flag is **not persisted
across container restarts**. After any `docker restart` / recreate / host
reboot, the `default` session comes back `WORKING` but with `config: null`, and
every store-backed call (`list_chats`, `list_contacts`, and even `get_messages`
for a single chat by JID) fails with HTTP 400:

```
Enable NOWEB store "config.noweb.store.enabled=True" and
"config.noweb.store.full_sync=True" when starting a new session.
```

The synced data is fine on disk (`/app/.sessions/noweb/default/store.sqlite3`);
only the session flag is lost. The fix is to re-PUT the session config — it
**preserves authentication (no QR) and does not lose history**:

```bash
curl -X PUT http://localhost:3000/api/sessions/default \
  -H "X-Api-Key: $WAHA_API_KEY" -H "Content-Type: application/json" \
  -d '{"config":{"noweb":{"store":{"enabled":true,"fullSync":true}}}}'
```

`ensure-noweb-store.sh` does this idempotently — it only PUTs when
`/api/default/chats?limit=1` is not already 200, so a healthy session is never
needlessly restarted.

## Install on the VPS

These files live in this repo as a record; the live copies are deployed at the
paths below (WAHA is managed from `/opt/whatsapp-bot/deploy`).

```bash
sudo install -m 0755 deploy/ensure-noweb-store.sh /opt/whatsapp-bot/deploy/ensure-noweb-store.sh
sudo cp deploy/noweb-store-ensure.service /etc/systemd/system/
sudo cp deploy/noweb-store-ensure.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now noweb-store-ensure.timer
```

The timer fires 90 s after boot and then every 10 min. To force a heal
immediately after a manual WAHA restart:

```bash
sudo systemctl start noweb-store-ensure.service
```

> To find a **person**, use `whatsapp_list_contacts`: NOWEB chat objects carry
> `name: null` for individuals, so `whatsapp_list_chats name_contains` only
> matches group names.
