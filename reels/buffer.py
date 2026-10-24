"""Plant Videos über die Buffer-API (GraphQL) ein: TikTok und Instagram in einem Schritt.

Buffer holt das Video zur Veröffentlichung von einer öffentlichen URL (hier: GitHub Pages).
Kostenloser Buffer-Tarif: 3 Kanäle, 3.000 API-Anfragen pro 30 Tage.
"""
import json
import urllib.request

API = "https://api.buffer.com"


def _gql(key, query, variables=None):
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    req = urllib.request.Request(API, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    if data.get("errors"):
        raise RuntimeError(f"Buffer-Fehler: {data['errors']}")
    return data["data"]


def channels(key):
    """Alle verbundenen Kanäle (id, Dienst, Name) über alle Organisationen des Kontos."""
    orgs = _gql(key, "query { account { organizations { id } } }")["account"]["organizations"]
    out = []
    for org in orgs:
        q = "query { channels(input: {organizationId: %s}) { id service name } }" % json.dumps(org["id"])
        out += _gql(key, q)["channels"]
    return out


def queue_video(key, channel_id, text, video_url, thumb_ms=1500):
    # Werte direkt eingesetzt (json.dumps escaped die Strings), Enums ohne Anführungszeichen
    q = """mutation {
      createPost(input: {
        text: %s
        channelId: %s
        schedulingType: automatic
        mode: addToQueue
        assets: [{ video: { url: %s, metadata: { thumbnailOffset: %d } } }]
      }) {
        ... on PostActionSuccess { post { id } }
        ... on MutationError { message }
      }
    }""" % (json.dumps(text), json.dumps(channel_id), json.dumps(video_url), thumb_ms)
    res = _gql(key, q)["createPost"]
    if "message" in res:
        raise RuntimeError(f"Buffer hat den Post abgelehnt: {res['message']}")
    return res["post"]["id"]
