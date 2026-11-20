# Adding a language

The app ships in English (`en`) and Hindi (`hi`). Visitors, guards and hosts see every
screen in either; the admin dashboard and the platform console are English only. This
guide adds a third language, Odia (`or`) as the example. Two tests fail until every
string is translated, so you can't ship half a language by accident.

Have a native speaker review every string before going live. Visitors read the privacy
notice in this language, and under the DPDP Act it must be clear and accurate.

## 1. Web screens (visitor, guard, host)

1. Copy the English files in `web/src/locales/` and translate the values (never the
   keys). Keep every `{{placeholder}}` exactly as it is.

   | English | New file | Used by |
   |---|---|---|
   | `en.json` | `or.json` | sign-in, navigation |
   | `visit.en.json` | `visit.or.json` | check-in, pass, host response page, privacy page |
   | `staff.en.json` | `staff.or.json` | guard console, host app |

   The files are picked up by name, so they need no registration.
2. Add the language to the switcher in `web/src/lib/i18n.ts`:

   ```ts
   export const LANGUAGES = [
     { code: "en", label: "English" },
     { code: "hi", label: "हिन्दी" },
     { code: "or", label: "ଓଡ଼ିଆ" },
   ] as const;
   ```
3. Run `npm test`. `src/locales/locales.test.ts` checks that each file has every
   English key, with the same placeholders, and none left empty.

Plural keys (`_one` / `_other`) follow [i18next's plural rules](https://www.i18next.com/translation-function/plurals)
for the language. Some languages need other suffixes (`_few`, `_many`); add them as the
rules require.

## 2. API (WhatsApp messages, privacy notice)

1. Add the code in `api/app/core/i18n.py`:

   ```python
   Locale = Literal["en", "hi", "or"]
   LOCALES: tuple[str, ...] = ("en", "hi", "or")
   ```
   Every request schema and the org's `enabled_locales` setting use this, so the new
   code is accepted everywhere at once.
2. Translate, adding an `"or"` entry next to every `"hi"` one:
   - `app/notifications/templates.py`: `TEMPLATES`, `BUTTONS` (20 characters at most,
     a WhatsApp limit), `OUTCOMES`. These are what the dev inbox shows and what goes out
     as free text inside the 24-hour window.
   - `app/notifications/meta.py`: each template's `body`. These are the texts Meta
     approves, so they follow Meta's rules: positional `{{1}}`, `{{2}}`… in increasing
     order, never at the very start or end of the text. Also add the short labels near the
     top (`NO_DETAILS`, `DETAILS_BTN`, `PASS_BTN`, `SAID`, `FOOTER`) and the fallback
     texts inside `SPECS`. Anything missing falls back to English.
   - `app/services/consent.py`: `DEFAULT_NOTICE`, the privacy notice new orgs start with
     (existing orgs publish their own version under **Privacy → Privacy notice**).
   - `app/services/visits.py`: `DETAIL`, the extra lines in a host's request.
   - `app/services/orgs.py`: the default purposes' `label_i18n`.
   - `app/services/invites.py`: `when_text`, if the date wording differs.
3. Run `pytest tests/test_whatsapp.py`. `test_every_language_has_every_message` checks
   that every message, button and notice has the new language with the same placeholders.

## 3. WhatsApp templates in Meta

Business-initiated messages only go out through templates that Meta has approved, one
per language. After deploying:

```bash
python -m scripts.whatsapp_templates print     # review the JSON for the new language
python -m scripts.whatsapp_templates create    # submit (existing ones report an error and are left alone)
python -m scripts.whatsapp_templates status    # wait until every row says APPROVED
```

Use the language code Meta expects. Check
[Meta's supported languages](https://developers.facebook.com/docs/whatsapp/business-management-api/message-templates/supported-languages);
if it differs from yours, map it in `meta.lang()`. Until the templates are approved,
messages in the new language fail with error #132001 (template not found), shown under
**Shared WhatsApp number** in the platform console. Turn the language on for an org only
after that.

The verification code (`vms_otp`) is an authentication template: Meta writes its text,
so there is nothing to translate there.

## 4. Turn it on

Each org chooses the languages its visitors can pick (`enabled_locales` in its settings)
and its default language (`default_locale`). Hosts and guards switch language with the
button at the top of their screens; the choice is remembered on that device.

QR posters print English and Hindi. To add a third language there, add a line to the
headline and to `STEPS` in `app/services/posters.py`, then check that the A4 page still
fits.
