"""WhatsApp Cloud API: template definitions and request building.

Business-initiated messages must use a template that Meta has approved. Each entry in
``SPECS`` is one template: its Meta name (``WHATSAPP_TEMPLATE_PREFIX`` + key), category,
body text per language with positional ``{{n}}`` variables, and buttons. The same
definitions are used to *create* the templates (``python -m scripts.whatsapp_templates``)
and to *send* them, so the two can't drift apart.

The bodies follow Meta's rules: variables are never empty, never contain new lines or
tabs (the ``value`` helpers below clean them), and a body never starts or ends with a
variable. Links are URL buttons whose dynamic part is everything after
``PUBLIC_WEB_URL/``, so the message shows a button instead of a long URL.

Visitor photos are deliberately *not* sent as an image header: a photo sent into a
host's WhatsApp chat stays on their phone forever, outside the retention period. The
"See details" button opens the photo behind a signed link that stops working instead.

Replies to a host's tap (``response_ack``, ``response_too_late``) are sent as plain
text: the host has just messaged us, so the 24-hour customer-service window is open.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.i18n import LOCALES
from app.notifications.templates import BUTTONS, pick

P = dict[str, str]

# Messages sent as free-form text, only inside the 24-hour window.
SESSION_ONLY = {"response_ack", "response_too_late", "optout_ack", "optin_ack"}


def line(s: str, limit: int = 300) -> str:
    """One line, as Meta requires for variables: no new lines, tabs or runs of spaces."""
    s = re.sub(r"\s*[\r\n\t]+\s*", " · ", s.strip())
    s = re.sub(r" {2,}", " ", s).strip(" ·")
    return s[: limit - 1] + "…" if len(s) > limit else s


def bare(s: str) -> str:
    """Our message params carry their own punctuation (", Acme", " (Main gate)").
    Strip it so the value can stand alone inside a template."""
    return line(re.sub(r"^[\s,(]+|[\s)]+$", "", s or ""))


def or_(value: str, fallback: dict[str, str]) -> Callable[[P, str], str]:
    """A variable with a localized fallback, because Meta rejects empty variables."""
    return lambda p, loc: bare(p.get(value, "")) or pick(fallback, loc)


def v(key: str) -> Callable[[P, str], str]:
    return lambda p, loc: bare(p.get(key, "")) or "-"  # noqa: ARG005


def joined(*keys: str, sep: str = ", ") -> Callable[[P, str], str]:
    return lambda p, loc: sep.join(x for k in keys if (x := bare(p.get(k, "")))) or "-"  # noqa: ARG005


def quoted(key: str, fallback: dict[str, str], label: dict[str, str]) -> Callable[[P, str], str]:
    """The host's optional message: 'They said: “…”.' or a polite default."""

    def f(p: P, loc: str) -> str:
        m = bare(p.get(key, "")).strip('“”"')
        return f"{pick(label, loc)} “{m}”." if m else pick(fallback, loc)

    return f


@dataclass(frozen=True)
class Spec:
    category: str  # UTILITY | AUTHENTICATION
    body: dict[str, str]  # locale -> text with {{1}}, {{2}}, ...
    vars: tuple[Callable[[P, str], str], ...] = ()
    quick_replies: bool = False  # the message's action buttons (Approve / Wait / Reject)
    url_param: str | None = None  # param holding a link under PUBLIC_WEB_URL
    url_title: dict[str, str] = field(default_factory=dict)
    footer: dict[str, str] = field(default_factory=dict)


NO_DETAILS = {"en": "No other details.", "hi": "कोई अन्य विवरण नहीं।"}
DETAILS_BTN = {"en": "See details", "hi": "विवरण देखें"}
PASS_BTN = {"en": "View pass", "hi": "पास देखें"}
SAID = {"en": "Their message:", "hi": "उनका संदेश:"}
FOOTER = {"en": "Visitor desk", "hi": "विज़िटर डेस्क"}

# The visitor block shared by the three "please respond" templates.
_VISITOR_VARS = (
    joined("visitor", "company"),
    v("purpose"),
    or_("details", NO_DETAILS),
)

SPECS: dict[str, Spec] = {
    # Authentication templates have fixed, Meta-provided text in every language. The
    # code fills the body and the copy-code button.
    "otp": Spec(
        category="AUTHENTICATION",
        body={
            "en": "*{{1}}* is your verification code. For your security, do not share this code.",
            "hi": "*{{1}}* आपका सत्यापन कोड है। अपनी सुरक्षा के लिए यह कोड किसी के साथ साझा न करें।",
        },
        vars=(v("code"),),
    ),
    "visit_request": Spec(
        category="UTILITY",
        body={
            "en": "Visitor for you at {{1}}.\n\n*{{2}}*\nPurpose: {{3}}\n{{4}}\n\n"
            "Reply with a button, or open the details to see their photo.",
            "hi": "नया आगंतुक: {{1}} पर आपसे मिलने कोई आया है।\n\n*{{2}}*\nउद्देश्य: "
            "{{3}}\n{{4}}\n\n"
            "बटन से जवाब दें, या उनकी फ़ोटो देखने के लिए विवरण खोलें।",
        },
        vars=(joined("site", "gate"), *_VISITOR_VARS),
        quick_replies=True,
        url_param="link",
        url_title=DETAILS_BTN,
        footer=FOOTER,
    ),
    "visit_escalated": Spec(
        category="UTILITY",
        body={
            "en": "Visitor waiting: {{1}} has not responded to a visitor at {{2}}. Can you take "
            "them?\n\n"
            "*{{3}}*\nPurpose: {{4}}\n{{5}}\n\nReply with a button, or open the details "
            "to see their photo.",
            "hi": "आगंतुक इंतज़ार में: {{1}} ने {{2}} पर आए आगंतुक को जवाब नहीं दिया है। क्या "
            "आप उनसे मिल "
            "सकते हैं?\n\n*{{3}}*\nउद्देश्य: {{4}}\n{{5}}\n\nबटन से जवाब दें, या उनकी "
            "फ़ोटो देखने के लिए विवरण खोलें।",
        },
        vars=(v("host"), joined("site", "gate"), *_VISITOR_VARS),
        quick_replies=True,
        url_param="link",
        url_title=DETAILS_BTN,
        footer=FOOTER,
    ),
    "visit_reminder": Spec(
        category="UTILITY",
        body={
            "en": "Reminder from the gate at {{1}}: *{{2}}* is still waiting for you.\n"
            "Purpose: {{3}}\n{{4}}\n\nPlease reply with a button.",
            "hi": "याद दिलाना: {{1}} गेट से *{{2}}* अभी भी आपका इंतज़ार कर रहे हैं।\n"
            "उद्देश्य: {{3}}\n{{4}}\n\nकृपया बटन से जवाब दें।",
        },
        vars=(joined("site", "gate"), *_VISITOR_VARS),
        quick_replies=True,
        url_param="link",
        url_title=DETAILS_BTN,
        footer=FOOTER,
    ),
    "visit_approved": Spec(
        category="UTILITY",
        body={
            "en": "Good news: {{1}} has approved your visit to {{2}}. Show your pass at the gate.",
            "hi": "खुशखबरी: {{1}} ने {{2}} पर आपकी विज़िट स्वीकृत कर दी है। गेट पर अपना पास दिखाएँ।",
        },
        vars=(v("host"), v("site")),
        url_param="pass_url",
        url_title=PASS_BTN,
    ),
    "visit_waiting": Spec(
        category="UTILITY",
        body={
            "en": "Update on your visit: {{1}} has seen your request and asks you to wait a few "
            "minutes. {{2}} "
            "We will message you here when they respond.",
            "hi": "आपकी विज़िट की जानकारी: {{1}} ने आपका अनुरोध देख लिया है और कुछ मिनट रुकने "
            "को कहा है। {{2}} "
            "जवाब आते ही हम आपको यहाँ बताएँगे।",
        },
        vars=(
            v("host"),
            quoted(
                "message",
                {"en": "Please stay at reception.", "hi": "कृपया रिसेप्शन पर रहें।"},
                SAID,
            ),
        ),
    ),
    "visit_rejected": Spec(
        category="UTILITY",
        body={
            "en": "Update on your visit: {{1}} can't meet you right now. {{2}} Please check "
            "with reception at {{3}}.",
            "hi": "आपकी विज़िट की जानकारी: {{1}} अभी आपसे नहीं मिल सकते। {{2}} कृपया {{3}} के "
            "रिसेप्शन से संपर्क करें।",
        },
        vars=(
            v("host"),
            quoted("message", {"en": "Sorry about that.", "hi": "हमें खेद है।"}, SAID),
            v("site"),
        ),
    ),
    "visit_expired": Spec(
        category="UTILITY",
        body={
            "en": "We could not reach {{1}} in time. Please check with reception at {{2}}.",
            "hi": "हम समय पर {{1}} से संपर्क नहीं कर पाए। कृपया {{2}} के रिसेप्शन से संपर्क करें।",
        },
        vars=(v("host"), v("site")),
    ),
    "visitor_arrived": Spec(
        category="UTILITY",
        body={
            "en": "Your visitor *{{1}}* has checked in at {{2}}.\n{{3}}\n\nNo action is needed.",
            "hi": "आपके आगंतुक *{{1}}* {{2}} पर अंदर आ गए हैं।\n{{3}}\n\nकोई कार्रवाई ज़रूरी नहीं है।",
        },
        vars=(
            joined("visitor", "company"),
            joined("site", "gate"),
            lambda p, loc: (
                f"{pick({'en': 'Note from security:', 'hi': 'सुरक्षा की टिप्पणी:'}, loc)} "
                f"{n.split(':', 1)[-1].strip()}."
                if (n := bare(p.get("note", "")))
                else pick({"en": "No notes from security.", "hi": "सुरक्षा की कोई टिप्पणी नहीं।"}, loc)
            ),
        ),
        footer=FOOTER,
    ),
    "invite": Spec(
        category="UTILITY",
        body={
            "en": "Invitation: {{1}} has invited you to {{2}}, {{3}}, {{4}}. {{5}}\n\nShow your "
            "pass "
            "at the gate. There is no need to wait for approval.",
            "hi": "आमंत्रण: {{1}} ने आपको {{2}}, {{3}} पर आमंत्रित किया है ({{4}})। "
            "{{5}}\n\nगेट पर "
            "अपना पास दिखाएँ। स्वीकृति का इंतज़ार नहीं करना होगा।",
        },
        vars=(
            v("host"),
            v("org"),
            v("site"),
            lambda p, loc: bare(re.sub(r"^\s*on\s+", "", p.get("when", ""))) or "-",  # noqa: ARG005
            lambda p, loc: (
                f"{pick({'en': 'About:', 'hi': 'विषय:'}, loc)} {t}."
                if (t := bare(p.get("title", "")).rstrip("."))
                else pick({"en": "See you there.", "hi": "आपका स्वागत है।"}, loc)
            ),
        ),
        url_param="pass_url",
        url_title=PASS_BTN,
    ),
    "invite_cancelled": Spec(
        category="UTILITY",
        body={
            "en": "Your invitation from {{1}} to {{2}} has been cancelled.",
            "hi": "सूचना: {{1}} की ओर से {{2}} का आपका आमंत्रण रद्द कर दिया गया है।",
        },
        vars=(v("host"), v("site")),
    ),
    "evacuation": Spec(
        category="UTILITY",
        body={
            "en": "EVACUATION at {{1}}, {{2}}. {{3}} visitors are checked in ({{4}} people "
            "including those with them). Sent by {{5}}. Open the live list with phone "
            "numbers below.",
            "hi": "निकासी: {{1}}, {{2}}। {{3}} आगंतुक अंदर हैं (साथ आए लोगों सहित {{4}} "
            "लोग)। {{5}} द्वारा भेजा गया। फ़ोन नंबर के साथ लाइव सूची नीचे खोलें।",
        },
        vars=(v("site"), v("time"), v("visits"), v("people"), v("by")),
        url_param="link",
        url_title={"en": "Live list", "hi": "लाइव सूची"},
    ),
    "login_link": Spec(
        category="UTILITY",
        body={
            "en": "Sign in to {{1}} visitor management with the button below. The link "
            "works once and expires in 15 minutes. If you didn't ask for it, ignore "
            "this message.",
            "hi": "नीचे दिए बटन से {{1}} विज़िटर मैनेजमेंट में साइन इन करें। यह लिंक एक बार "
            "चलेगा और 15 मिनट में समाप्त हो जाएगा। अगर आपने यह नहीं माँगा, तो इसे "
            "अनदेखा करें।",
        },
        vars=(v("org"),),
        url_param="link",
        url_title={"en": "Sign in", "hi": "साइन इन करें"},
    ),
}

SPECS["privacy_erased"] = Spec(
    category="UTILITY",
    body={
        "en": "Your data request is done: {{1}} has erased your visitor data, as you asked. "
        "Your past visits are kept only as anonymous counts.",
        "hi": "आपका डेटा अनुरोध पूरा हुआ: आपके अनुरोध के अनुसार {{1}} ने आपका विज़िटर डेटा "
        "हटा दिया है। आपकी पिछली विज़िट केवल गुमनाम गिनती के रूप में रखी गई हैं।",
    },
    vars=(v("org"),),
)
SPECS["privacy_rejected"] = Spec(
    category="UTILITY",
    body={
        "en": "Update on your data request: {{1}} could not erase your visitor data. "
        "Reason: {{2}} For questions, contact {{3}}.",
        "hi": "आपके डेटा अनुरोध की जानकारी: {{1}} आपका विज़िटर डेटा नहीं हटा सका। कारण: "
        "{{2}} प्रश्नों के लिए {{3}} से संपर्क करें।",
    },
    vars=(
        v("org"),
        v("note"),
        or_("contact", {"en": "the reception desk", "hi": "रिसेप्शन"}),
    ),
)

LANGUAGES = LOCALES  # every template is created in each supported language
QUICK_REPLY_ACTIONS = ("approve", "wait", "reject")


def template_name(key: str) -> str:
    return f"{get_settings().whatsapp_template_prefix}{key}"


def web_base() -> str:
    return get_settings().public_web_url.rstrip("/") + "/"


def url_suffix(link: str) -> str:
    """The dynamic part of a URL button (the template stores PUBLIC_WEB_URL/{{1}})."""
    base = web_base()
    if not link.startswith(base):
        raise ValueError(f"link is not under PUBLIC_WEB_URL: {link[:60]}")
    return link[len(base) :]


def lang(locale: str) -> str:
    return locale if locale in LANGUAGES else "en"


def values(spec: Spec, params: P, locale: str) -> list[str]:
    return [line(f(params, locale)) or "-" for f in spec.vars]


def message_payload(
    to: str,
    key: str,
    locale: str,
    params: P,
    text: str,
    buttons: list[dict[str, str]],
) -> dict[str, Any]:
    """The JSON body for POST /{phone_number_id}/messages."""
    base: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to.lstrip("+"),
    }
    if key in SESSION_ONLY:
        return {**base, "type": "text", "text": {"preview_url": False, "body": text[:4096]}}
    spec = SPECS[key]
    loc = lang(locale)
    components: list[dict[str, Any]] = []
    if spec.vars:
        components.append(
            {
                "type": "body",
                "parameters": [{"type": "text", "text": t} for t in values(spec, params, loc)],
            }
        )
    if spec.category == "AUTHENTICATION":
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": params.get("code", "")}],
            }
        )
    index = 0
    if spec.quick_replies:
        for b in buttons:
            components.append(
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": str(index),
                    "parameters": [{"type": "payload", "payload": b["id"]}],
                }
            )
            index += 1
    if spec.url_param:
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": str(index),
                "parameters": [
                    {"type": "text", "text": url_suffix(params.get(spec.url_param, ""))}
                ],
            }
        )
    return {
        **base,
        "type": "template",
        "template": {
            "name": template_name(key),
            "language": {"code": loc},
            "components": components,
        },
    }


# ---------- Template creation (used by scripts/whatsapp_templates.py) ----------

EXAMPLE: P = {
    "code": "482913",
    "org": "Kalinga Steel",
    "site": "Bhubaneswar HQ",
    "gate": "Main gate",
    "visitor": "Ravi Kumar",
    "company": ", Acme Logistics",
    "purpose": "Meeting",
    "details": "\nVehicle: OD02AB1234",
    "host": "Meera Das",
    "message": " “Five minutes please”",
    "note": "",
    "when": " on 21 Nov, 10:00–12:00",
    "title": " Quarterly review.",
    "time": "11:42 AM",
    "visits": "14",
    "people": "17",
    "by": "Anil (Security)",
}


def create_payload(key: str, locale: str) -> dict[str, Any]:
    """The JSON for POST /{waba_id}/message_templates (one language of one template)."""
    spec = SPECS[key]
    loc = lang(locale)
    name = template_name(key)
    if spec.category == "AUTHENTICATION":
        return {
            "name": name,
            "language": loc,
            "category": "AUTHENTICATION",
            "message_send_ttl_seconds": 300,
            "components": [
                {"type": "BODY", "add_security_recommendation": True},
                {"type": "FOOTER", "code_expiration_minutes": 5},
                {"type": "BUTTONS", "buttons": [{"type": "OTP", "otp_type": "COPY_CODE"}]},
            ],
        }
    components: list[dict[str, Any]] = [
        {
            "type": "BODY",
            "text": spec.body[loc],
            **({"example": {"body_text": [values(spec, EXAMPLE, loc)]}} if spec.vars else {}),
        }
    ]
    if spec.footer:
        components.append({"type": "FOOTER", "text": pick(spec.footer, loc)})
    btns: list[dict[str, Any]] = []
    if spec.quick_replies:
        btns += [
            {"type": "QUICK_REPLY", "text": pick(BUTTONS[a], loc)} for a in QUICK_REPLY_ACTIONS
        ]
    if spec.url_param:
        btns.append(
            {
                "type": "URL",
                "text": pick(spec.url_title, loc),
                "url": web_base() + "{{1}}",
                "example": [web_base() + "r/example-token"],
            }
        )
    if btns:
        components.append({"type": "BUTTONS", "buttons": btns})
    return {"name": name, "language": loc, "category": spec.category, "components": components}
