# Co dnes k obědu?

První funkční verze pro kolegy: AB Slušovice, SUD Slušovice, Přerovská restaurace. Jedna společná sada oblíbených jídel a týdenní nahrání Wordu správcem.

## Lokální spuštění

Potřebujete Python 3.12+, `antiword` a balíčky z `requirements.txt`.

```bash
pip install -r requirements.txt
export ADMIN_PASSWORD='zvolte-silne-heslo'
python app.py
```

Otevřete http://127.0.0.1:5000. Pro místní testování se stav ukládá do `state.json`.

## Veřejné nasazení a společné úložiště

1. Založte projekt na **Supabase** a v SQL editoru spusťte `supabase.sql`.
2. Vložte projekt na GitHub (bez souborů `.env` a `state.json`).
3. Na **Render** založte nový **Web Service** z repozitáře a vyberte Docker. Provoz zdarma je možný podle aktuálních podmínek tarifu.
4. Nastavte tajné proměnné `ADMIN_PASSWORD`, `SUPABASE_URL` a `SUPABASE_SERVICE_ROLE_KEY` z projektu Supabase.
5. Po nasazení dostanete veřejný odkaz. Ten rozešlete kolegům. Pouze správce zadává heslo v části Správa.

**Pozor:** bez nastaveného Supabase je ukládání na hostingu s dočasným diskem nespolehlivé. Heslo nesmí být veřejné a service role key nikdy nevkládejte do webové stránky.

## Omezení první verze

- AB se čte přímo z webu. Web publikuje jeden aktuální den a běžně neuvádí ceny.
- SUD zveřejňuje PDF. Aplikace se pokouší získat text z PDF, ale pokud je PDF jen obrázek, nebude automatické rozpoznávání fungovat. V tom případě ukáže stav chyby, ne vymyšlená jídla. Strukturu konkrétního PDF je třeba po nasazení ověřit a případně upravit parser.
- Přerovská podporuje `.doc` i `.docx`, zpracovává rozpis po dnech a ceny 165 Kč; zvláštní příplatky se zatím nepřičítají automaticky. Objednávka den předem má podle dodaného souboru cenu 150 Kč.
- Zdrojové weby mohou kdykoli změnit formát. Automatické načítání je nejlepší otestovat na běžícím serveru.
- Není implementována správa uživatelů. Pro nahrání a úpravu společných preferencí se používá jediné administrátorské heslo.
