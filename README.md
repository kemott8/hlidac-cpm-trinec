# Hlídač registrace CPM Třinec

Každých ~15 minut kontroluje web [Centra preventivní medicíny](https://cpm.npo.agel.cz/moznosti-prihlaseni)
a pošle push notifikaci do aplikace **ntfy**, jakmile se u pracoviště Třinec něco změní.

## Co se hlídá

- text záložky **Pracoviště Třinec** na stránce Možnosti přihlášení,
- dotazníky na `dotazniky.agel.cz` (`npo/cpm`, `NPO/cpm-trinec` a každý nový odkaz, který se na webu objeví; Ostrava se ignoruje).

## Notifikace

| Situace | Priorita |
|---|---|
| 🔴 Dotazník je otevřený k vyplnění – chodí **při každém běhu**, dokud je otevřený | urgentní |
| 🔴 U Třince se objevil odkaz na registraci | urgentní |
| 🟠 Oznámen konkrétní termín (datum / čas) | vysoká |
| 🟡 Jiná změna textu nebo stavu dotazníku | normální |
| ⚠️ Web nejde načíst ~1 hodinu | vysoká |
| ✅ Ranní potvrzení „hlídač běží“ (jednou denně po 8:00) | nízká |

## Nastavení

- `Settings → Secrets and variables → Actions → NTFY_TOPIC` – název tématu v ntfy.
- (volitelně) `NTFY_EMAIL` – e-mail, kam ntfy přepošle důležité notifikace.

## Ovládání

- Ruční kontrola / zkušební notifikace: **Actions → Hlídač CPM Třinec → Run workflow** (zaškrtnout „Poslat zkušební notifikaci“).
- **Po přihlášení hlídač vypněte:** Actions → Hlídač CPM Třinec → ⋯ → Disable workflow.

Stav z minulého běhu je v `state.json` (commituje se automaticky).
