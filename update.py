"""Rendimiento YTD Afores (diario).
Baja el precio de bolsa diario de las 100 Siefores Básicas desde la BMV, lo guarda en prices.json
y genera data.json para index.html. Corre en GitHub Actions; sin dependencias externas."""
import json, os, sys, time, datetime as dt, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
URL = 'https://www.bmv.com.mx/es/Grupo_BMV/GraficaHistorica?idSitioPagina=1&idEmision={}'
URL_HOY = 'https://www.bmv.com.mx/es/Grupo_BMV/BmvJsonGeneric?idSitioPagina=1&bandera=1&idEmisora={}&idEmision={}'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'


def load(name, default=None):
    p = os.path.join(ROOT, name)
    if not os.path.exists(p):
        return default
    with open(p, encoding='utf-8') as f:
        return json.load(f)


def save(name, obj):
    with open(os.path.join(ROOT, name), 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))


def get_json(url, tries=3):
    last = None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json,text/plain,*/*'})
            with urllib.request.urlopen(req, timeout=40) as r:
                txt = r.read().decode('utf-8', 'replace')
            return json.loads(txt[txt.index('{'): txt.rindex('}') + 1])   # quita "for(;;);(" y el comentario final
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * (k + 1))
    raise RuntimeError(f'{url}: {last}')


def day(ts):
    return dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime('%Y-%m-%d')


def fetch(id_emision):
    """Historia diaria (~1 año) de una serie BMV: {AAAA-MM-DD: precio}."""
    pts = get_json(URL.format(id_emision))['response']['datosGrafica']['mapaValoresGraficaVolumen']
    return {day(ts): float(v) for ts, v in pts if v is not None}


def fetch_today(id_emisora, id_emision):
    """Precio del día (la BMV lo publica de madrugada, antes de que entre a la historia)."""
    pts = get_json(URL_HOY.format(id_emisora, id_emision))['response']['datosGrafica']['mapaValoresGrafica']
    return {day(ts): float(v) for ts, v in pts if v is not None}


def update_prices(cfg, prices):
    errors = []
    for key, fund in cfg['funds'].items():
        try:
            new = fetch(fund['idEmision'])
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            continue
        try:                                   # precio de hoy, si aún no está en la historia
            hoy = fetch_today(fund['idEmisora'], fund['idEmision'])
            new.update({d: v for d, v in hoy.items() if not new or d > max(new)})
        except Exception as e:  # noqa: BLE001
            errors.append('hoy ' + str(e))
        prices.setdefault(key, {}).update(new)
        time.sleep(0.3)
    return errors


def build(cfg, prices):
    afores, siefores = cfg['afores'], cfg['siefores']
    keys = [[f'{a}|{s}' for a in range(len(afores))] for s in range(len(siefores))]
    all_dates = sorted({d for k in prices for d in prices[k]})
    year = max(all_dates)[:4]
    base = max(d for d in all_dates if d < f'{year}-01-01')          # último día hábil del año anterior
    dates = [d for d in all_dates if d >= base]

    def series(k):                                                  # precio con relleno hacia adelante
        p, out, last = prices.get(k, {}), [], None
        for d in dates:
            last = p.get(d, last)
            out.append(last)
        return out

    ytd = []
    for s in range(len(siefores)):
        row = []
        for a in range(len(afores)):
            px = series(keys[s][a])
            b = px[0]
            if b is None:
                raise RuntimeError(f'sin precio base para {afores[a]} {siefores[s]}')
            row.append([round((v / b - 1) * 100, 4) if v is not None else None for v in px])
        ytd.append(row)
    return {
        'updated': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'base': base, 'asof': dates[-1], 'dates': dates,
        'afores': afores, 'siefores': siefores,
        'ytd': ytd,                        # [siefore][afore][fecha], % YTD
        'an': cfg['an'],                   # {"AAAA-MM": [siefore][afore]} activos netos, mdp
        'r12': cfg['r12'],                 # {"AAAA-MM": [siefore][afore]} rendimiento 12m CONSAR, %
    }


def main():
    cfg = load('config.json')
    prices = load('prices.json', {})
    errors = [] if '--offline' in sys.argv else update_prices(cfg, prices)
    save('prices.json', prices)
    data = build(cfg, prices)
    save('data.json', data)
    print(f"ok: {len(prices)} fondos, base {data['base']}, ultimo {data['asof']}, errores {len(errors)}")
    for e in errors:
        print('  ', e)
    if len(errors) > 10:                    # si la BMV falla en masa, que el workflow lo marque en rojo
        sys.exit(1)


if __name__ == '__main__':
    main()
