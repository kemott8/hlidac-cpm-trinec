# Hlídače (CPM Třinec + cena Shilajit)

Dva hlídače běžící zdarma v GitHub Actions. Notifikace chodí do aplikace **ntfy** – jen když se opravdu něco děje, žádné denní zprávy.

## 1. Registrace CPM Třinec (každých ~15 min)

Hlídá [Možnosti přihlášení](https://cpm.npo.agel.cz/moznosti-prihlaseni) – text záložky **Pracoviště Třinec**
a dotazníky na `dotazniky.agel.cz` (`npo/cpm`, `NPO/cpm-trinec` a každý nový odkaz; Ostrava se ignoruje).

| Notifikace | Kdy |
|---|---|
| 🔴 **Registrace spuštěna** (urgentní) | dotazník je otevřený k vyplnění – první hodinu každých ~15 min, pak jednou za hodinu, dokud je otevřený |
| 🔴 Registrace nejspíš spuštěna (urgentní) | u Třince se objeví text „registrace je spuštěna / zaregistrujte se“ |
| 📢 Nové informace (jednou) | změní se text u Třince (např. oznámený termín) nebo stav dotazníku |

## 2. Cena IMMORTAL SHILAJIT 100 g (každé 4 hodiny)

Čte cenu 100g varianty z [adamraw.cz](https://www.adamraw.cz/immortal-shilajit-primal-alchemy/?variant=54).
💰 Notifikace přijde, když je cena **4 679 Kč a méně** (sleva ≥ 10 % z běžných 5 199 Kč) – jednou za akci,
znovu jen při dalším zlevnění. Historie cen je v `state_shilajit.json`.

## Když něco nefunguje

Když hlídač delší dobu nemůže web načíst (registrace ~1 h, Shilajit ~12 h), běh skončí chybou
a **GitHub pošle e-mail** – do telefonu nic nechodí.

## Ovládání

- **Test celé cesty:** Actions → Hlídač CPM Třinec → Run workflow → zaškrtnout „Poslat zkušební notifikaci“.
  Načte skutečný web, podvrhne otevřený dotazník pro Třinec a slevu 15 % na Shilajit a pošle dvě notifikace „🧪 TEST“.
  Skutečný stav hlídačů se tím nemění.
- Vypnutí (např. po přihlášení): **Actions → vybrat hlídač → ⋯ → Disable workflow**.
- Secrets: `NTFY_TOPIC` (téma v ntfy), volitelně `NTFY_EMAIL`.
