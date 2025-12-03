"""Landing page server for VK Ads redirects (FastAPI)."""

import json
import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from database.queries import create_vk_click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

VK_COUNTER_ID = os.getenv("VK_COUNTER_ID", "3723500")
BOT_URL = os.getenv("BOT_URL", "http://t.me/ClearTranscriptBot")
REDIRECT_DELAY_MS = int(os.getenv("VK_REDIRECT_DELAY_MS", "500"))
LISTEN_PORT = int(os.getenv("VK_SERVER_PORT", "8080"))

app = FastAPI(title="VK Ads landing")


@app.get("/vk-ads", response_class=HTMLResponse)
def vk_ads_landing(rb_clickid: str | None = None) -> HTMLResponse:
    if not rb_clickid:
        raise HTTPException(status_code=400, detail="rb_clickid is required")

    click = create_vk_click(rb_clickid)
    logging.info("VK Ads click registered: token=%s", click.token)

    token_json = json.dumps(click.token)
    counter_json = json.dumps(VK_COUNTER_ID)
    redirect_target = f"{BOT_URL}?start={click.token}"
    redirect_json = json.dumps(redirect_target)

    html = f"""
<!doctype html>
<html lang=\"ru\">
<head>
  <meta charset=\"utf-8\" />
  <title>Переход к боту</title>
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
</head>
<body>
<script type=\"text/javascript\">
  const clickToken = {token_json};
  const redirectTarget = {redirect_json};
  var _tmr = window._tmr || (window._tmr = []);
  _tmr.push({{id: {counter_json}, type: "pageView", start: (new Date()).getTime(), pid: clickToken}});
  (function (d, w, id) {{
    if (d.getElementById(id)) return;
    var ts = d.createElement("script"); ts.type = "text/javascript"; ts.async = true; ts.id = id;
    ts.src = "https://top-fwz1.mail.ru/js/code.js";
    var f = function () {{var s = d.getElementsByTagName("script")[0]; s.parentNode.insertBefore(ts, s);}};
    if (w.opera == "[object Opera]") {{ d.addEventListener("DOMContentLoaded", f, false); }} else {{ f(); }}
  }})(document, window, "tmr-code");
  setTimeout(() => {{ window.location.href = redirectTarget; }}, {REDIRECT_DELAY_MS});
</script>
<noscript><div><img src=\"https://top-fwz1.mail.ru/counter?id={VK_COUNTER_ID};js=na\" style=\"position:absolute;left:-9999px;\" alt=\"Top.Mail.Ru\" /></div></noscript>
</body>
</html>
"""

    return HTMLResponse(content=html, status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=LISTEN_PORT)
