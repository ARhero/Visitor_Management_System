"""Message templates (English / Hindi).

The text here is what the mock provider "sends" and what the dev inbox shows, and the
text sent inside the 24-hour window. With Meta, business-initiated messages use the
approved templates in ``meta.py`` instead, built from the same ``params``.
Button titles must stay at most 20 characters (WhatsApp limit).
"""

from typing import Any

TEMPLATES: dict[str, dict[str, str]] = {
    "otp": {
        "en": "{code} is your verification code for {org}. It expires in 5 minutes. "
        "Do not share it with anyone.",
        "hi": "{org} के लिए आपका सत्यापन कोड {code} है। यह 5 मिनट में समाप्त हो जाएगा। "
        "इसे किसी के साथ साझा न करें।",
    },
    "visit_request": {
        "en": "Visitor for you at {site} ({gate})\n\n*{visitor}*{company}\nPurpose: {purpose}"
        "{details}\n\nPhoto and details: {link}",
        "hi": "{site} ({gate}) पर आपसे मिलने कोई आया है\n\n*{visitor}*{company}\n"
        "उद्देश्य: {purpose}{details}\n\nफ़ोटो और विवरण: {link}",
    },
    "visit_escalated": {
        "en": "{host} has not responded. Can you take this visitor?\n\n*{visitor}*{company} "
        "at {site} ({gate})\nPurpose: {purpose}{details}\n\nPhoto and details: {link}",
        "hi": "{host} ने जवाब नहीं दिया है। क्या आप इस आगंतुक से मिल सकते हैं?\n\n"
        "*{visitor}*{company}, {site} ({gate})\nउद्देश्य: {purpose}{details}\n\n"
        "फ़ोटो और विवरण: {link}",
    },
    "visit_approved": {
        "en": "{host} has approved your visit to {site}. Show this pass at the gate:\n{pass_url}",
        "hi": "{host} ने {site} पर आपकी विज़िट स्वीकृत कर दी है। गेट पर यह पास दिखाएँ:\n{pass_url}",
    },
    "visit_waiting": {
        "en": "{host} has seen your request and asks you to wait a few minutes.{message}",
        "hi": "{host} ने आपका अनुरोध देख लिया है और कुछ मिनट रुकने को कहा है।{message}",
    },
    "visit_rejected": {
        "en": "{host} can't meet you right now.{message} Please check with reception at {site}.",
        "hi": "{host} अभी आपसे नहीं मिल सकते।{message} कृपया {site} के रिसेप्शन से संपर्क करें।",
    },
    "visit_expired": {
        "en": "We could not reach {host} in time. Please check with reception at {site}.",
        "hi": "हम समय पर {host} से संपर्क नहीं कर पाए। कृपया {site} के रिसेप्शन से संपर्क करें।",
    },
    "visit_reminder": {
        "en": "Reminder from the gate at {site}: *{visitor}*{company} is still waiting for "
        "you.\n\nPhoto and details: {link}",
        "hi": "{site} गेट से याद दिलाना: *{visitor}*{company} अभी भी आपका इंतज़ार कर रहे हैं।"
        "\n\nफ़ोटो और विवरण: {link}",
    },
    "visitor_arrived": {
        "en": "{visitor}{company} has checked in at {site}{gate}.{note}",
        "hi": "{visitor}{company} {site}{gate} पर अंदर आ गए हैं।{note}",
    },
    "invite": {
        "en": "{host} has invited you to {org}, {site}{when}.{title}\n\nShow this pass at "
        "the gate, no need to wait for approval:\n{pass_url}",
        "hi": "{host} ने आपको {org}, {site} पर आमंत्रित किया है{when}।{title}\n\nगेट पर यह पास "
        "दिखाएँ, स्वीकृति का इंतज़ार नहीं करना होगा:\n{pass_url}",
    },
    "invite_cancelled": {
        "en": "Your invitation from {host} to {site} has been cancelled.",
        "hi": "{host} की ओर से {site} का आपका आमंत्रण रद्द कर दिया गया है।",
    },
    "evacuation": {
        "en": "EVACUATION: {site} at {time}. {visits} visitors are checked in ({people} people "
        "including those with them). Live list with phone numbers: {link}\nSent by {by}.",
        "hi": "निकासी: {site}, {time}। {visits} आगंतुक अंदर हैं (साथ आए लोगों सहित {people} "
        "लोग)। फ़ोन नंबर के साथ लाइव सूची: {link}\n{by} द्वारा भेजा गया।",
    },
    "login_link": {
        "en": "Sign in to {org} visitor management: {link}\nThe link works once and expires "
        "in 15 minutes. If you didn't ask for it, ignore this message.",
        "hi": "{org} विज़िटर मैनेजमेंट में साइन इन करें: {link}\nयह लिंक एक बार चलेगा और 15 मिनट "
        "में समाप्त हो जाएगा। अगर आपने यह नहीं माँगा, तो इसे अनदेखा करें।",
    },
    "response_ack": {
        "en": "Done: {visitor} {outcome}.",
        "hi": "हो गया: {visitor} {outcome}।",
    },
    "response_too_late": {
        "en": "This request for {visitor} is already closed ({outcome}).",
        "hi": "{visitor} का यह अनुरोध पहले ही बंद हो चुका है ({outcome})।",
    },
    "privacy_erased": {
        "en": "{org} has erased your visitor data, as you asked. Your past visits are kept "
        "only as anonymous counts.",
        "hi": "आपके अनुरोध के अनुसार {org} ने आपका विज़िटर डेटा हटा दिया है। आपकी पिछली "
        "विज़िट केवल गुमनाम गिनती के रूप में रखी गई हैं।",
    },
    "privacy_rejected": {
        "en": "{org} could not erase your visitor data: {note} Questions: {contact}",
        "hi": "{org} आपका विज़िटर डेटा नहीं हटा सका: {note} प्रश्नों के लिए: {contact}",
    },
    "optout_ack": {
        "en": "You won't get any more messages from this number. Send START to turn them back on.",
        "hi": "अब आपको इस नंबर से कोई संदेश नहीं मिलेगा। फिर से शुरू करने के लिए START भेजें।",
    },
    "optin_ack": {
        "en": "Messages from this number are on again. Send STOP to turn them off.",
        "hi": "इस नंबर से संदेश फिर से चालू हो गए हैं। बंद करने के लिए STOP भेजें।",
    },
}

BUTTONS: dict[str, dict[str, str]] = {
    "approve": {"en": "Approve", "hi": "स्वीकृत करें"},
    "wait": {"en": "Ask to wait", "hi": "रुकने को कहें"},
    "reject": {"en": "Reject", "hi": "मना करें"},
}

OUTCOMES: dict[str, dict[str, str]] = {
    "approved": {"en": "approved", "hi": "स्वीकृत"},
    "waiting": {"en": "asked to wait", "hi": "को रुकने को कहा गया"},
    "rejected": {"en": "declined", "hi": "अस्वीकृत"},
    "expired": {"en": "expired", "hi": "समाप्त"},
    "cancelled": {"en": "cancelled by the visitor", "hi": "आगंतुक द्वारा रद्द"},
    "checked_in": {"en": "already checked in", "hi": "पहले ही अंदर आ चुके हैं"},
    "checked_out": {"en": "already left", "hi": "जा चुके हैं"},
}


def pick(table: dict[str, str], locale: str) -> str:
    return table.get(locale) or table["en"]


def render(key: str, locale: str, params: dict[str, Any]) -> str:
    return pick(TEMPLATES[key], locale).format_map(_Default(params))


class _Default(dict):
    def __missing__(self, key: str) -> str:
        return ""
