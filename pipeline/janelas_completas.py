"""Cria data/atlas.db: trechos de pelo menos 10 anos seguidos em que a estação tem precipitação E temperatura juntas.

Uma janela é um trecho de dias seguidos em que a estação tem as duas variáveis (observadas ou estimadas pelo
modelo, dentro das regras de preencher_ml.py: lacunas de até 30 dias). Precipitação e temperatura precisam
estar no mesmo período, porque a janela serve à classificação climática (Köppen).

A média mensal usa só meses inteiros dentro do trecho: total mensal de chuva e média mensal de temperatura.
Cada janela guarda quantos dias têm algum valor estimado, para o site mostrar essa parcela.
Também guarda a tendência (reta de mínimos quadrados da série anual), a classe de Köppen e os recordes do trecho.
Cada estação guarda ainda os recordes da série completa (janela_id nulo).

Entrada (somente leitura): data/combinado.db (tabelas estacoes e dados, já com as estimativas aceitas);
data/fonte.db (altitude da estação)
Saída: data/atlas.db, com as tabelas `estacoes`, `janelas` e `recordes`.

Uso (na raiz do projeto):
    python -m pipeline.janelas_completas               # cria atlas.db (recusa se já existir)
    python -m pipeline.janelas_completas --substituir  # apaga o atlas.db atual e recria
"""
from calendar import monthrange
from datetime import date
from itertools import groupby
from pathlib import Path
import json
import sqlite3
import sys

from pipeline.calculos import koppen, koppen_alternativas

ROOT = Path(__file__).resolve().parents[1]
ORIGEM = ROOT / 'data' / 'combinado.db'
FONTE = ROOT / 'data' / 'fonte.db'  # só para a altitude, que não está no combinado.db
DESTINO = ROOT / 'data' / 'atlas.db'
MIN_DIAS = 3652  # ~10 anos

SCHEMA = '''
CREATE TABLE estacoes (id INTEGER PRIMARY KEY, tipo TEXT, codigo TEXT, nome TEXT, latitude REAL, longitude REAL,
  altitude REAL);
CREATE TABLE janelas (id INTEGER PRIMARY KEY, estacao_id INTEGER NOT NULL,
  inicio TEXT NOT NULL, fim TEXT NOT NULL, dias INTEGER NOT NULL, meses INTEGER NOT NULL,
  chuva_mensal REAL NOT NULL, temperatura_mensal REAL NOT NULL, dias_estimados INTEGER NOT NULL,
  clima_chuva TEXT NOT NULL, clima_temperatura TEXT NOT NULL, serie_anual TEXT NOT NULL,
  tendencia TEXT NOT NULL, koppen TEXT NOT NULL, koppen_alternativas TEXT NOT NULL);
CREATE TABLE recordes (id INTEGER PRIMARY KEY, estacao_id INTEGER NOT NULL, janela_id INTEGER, grupos TEXT NOT NULL);
'''


def janelas(linhas):
    """linhas: (data, chuva, temperatura, estimado) só com dias em que as duas variáveis têm valor, em ordem de data.
    estimado = 1 se algum dos dois valores é estimado. Devolve (inicio, fim, dias, meses, chuva_mensal,
    temperatura_mensal, dias_estimados) de cada trecho de dias seguidos com pelo menos MIN_DIAS."""
    # Dentro de um trecho de dias seguidos, a data menos a posição é constante.
    chave = lambda iv: date.fromisoformat(iv[1][0]).toordinal() - iv[0]
    for _, grupo in groupby(enumerate(linhas), key=chave):
        grupo = [v for _, v in grupo]
        if len(grupo) < MIN_DIAS:
            continue
        por_mes = {}
        for data, chuva, temp, _ in grupo:
            por_mes.setdefault(data[:7], []).append((chuva, temp))
        completos_por_mes = {mes: dias for mes, dias in por_mes.items()
                             if len(dias) == monthrange(int(mes[:4]), int(mes[5:7]))[1]}  # só meses inteiros
        completos = list(completos_por_mes.values())
        chuva_mensal = sum(sum(c for c, _ in dias) for dias in completos) / len(completos)
        temp_mensal = sum(sum(t for _, t in dias) / len(dias) for dias in completos) / len(completos)
        # Climograma: média de cada mês do ano (jan a dez) entre os meses completos do trecho.
        clima_chuva, clima_temp = [], []
        for m in range(1, 13):
            do_mes = [dias for mes, dias in completos_por_mes.items() if int(mes[5:7]) == m]
            clima_chuva.append(round(sum(sum(c for c, _ in dias) for dias in do_mes) / len(do_mes), 3))
            clima_temp.append(round(sum(sum(t for _, t in dias) / len(dias) for dias in do_mes) / len(do_mes), 3))
        # Série anual para tendência: só anos com os 12 meses completos dentro do trecho. [ano, chuva total, temp. média].
        por_ano = {}
        for mes, dias in completos_por_mes.items():
            por_ano.setdefault(int(mes[:4]), []).append(dias)
        serie = [[ano, round(sum(sum(c for c, _ in d) for d in meses), 1),
                  round(sum(sum(t for _, t in d) / len(d) for d in meses) / 12, 3)]
                 for ano, meses in sorted(por_ano.items()) if len(meses) == 12]
        yield (grupo[0][0], grupo[-1][0], len(grupo), len(completos), round(chuva_mensal, 3), round(temp_mensal, 3),
               sum(e for _, _, _, e in grupo), json.dumps(clima_chuva), json.dumps(clima_temp), json.dumps(serie))


def tendencia(serie):
    """Reta de mínimos quadrados [intercepto, inclinação por ano] da chuva anual e da temperatura média anual."""
    def reta(pontos):
        n = len(pontos)
        mx = sum(x for x, _ in pontos) / n
        my = sum(y for _, y in pontos) / n
        b = sum((x - mx) * (y - my) for x, y in pontos) / sum((x - mx) ** 2 for x, _ in pontos)
        return [my - b * mx, b]
    return {'chuva': reta([(a[0], a[1]) for a in serie]), 'temp': reta([(a[0], a[2]) for a in serie])}


def _melhor(reg, campo, valor, rotulo, maior):
    """Guarda em reg[campo] o [valor, rótulo] mais alto (maior=True) ou mais baixo, se valor não for None."""
    if valor is None:
        return
    atual = reg.get(campo)
    if atual is None or (valor > atual[0] if maior else valor < atual[0]):
        reg[campo] = [valor, rotulo]


def agrupar_recordes(linhas):
    """linhas: (data, máxima, mínima, chuva, chuva_estimada, temperatura), em qualquer ordem.
    dia: recorde de cada dia do ano (temperatura máx. e mín. e chuva em 1 dia; chuva só de dias observados).
    mes: média mensal de temperatura e total mensal de chuva, mais alto e mais baixo, por mês do ano.
    ano: média de temperatura e total de chuva de cada ano com os 12 meses completos.
    geral: os mesmos recordes sobre todo o período. Valores de dia/mês/ano são [valor, data] ou [valor, mês] ou [valor, ano]."""
    geral, dia, mes_rec, meses = {}, {}, {}, {}
    for data, tmax, tmin, chuva, estimado, temp in linhas:
        reg = dia.setdefault(data[5:10], {})
        chuva_obs = None if estimado else chuva
        for alvo in (reg, geral):
            _melhor(alvo, 'tmax', tmax, data, True)
            _melhor(alvo, 'tmin', tmin, data, False)
            _melhor(alvo, 'chuva', chuva_obs, data, True)
        if chuva is not None and temp is not None:
            m = meses.setdefault(data[:7], {'chuva': 0.0, 'temp': [], 'dias': 0})
            m['chuva'] += chuva
            m['temp'].append(temp)
            m['dias'] += 1
    # Só meses inteiros, como no climograma.
    mensal = {ym: (sum(m['temp']) / len(m['temp']), m['chuva']) for ym, m in meses.items()
              if m['dias'] == monthrange(int(ym[:4]), int(ym[5:]))[1]}
    for ym, (tmed, total) in sorted(mensal.items()):
        reg = mes_rec.setdefault(ym[5:], {})
        for alvo in (reg, geral):
            for campo, valor, maior in (('tmed_mes_alta', tmed, True), ('tmed_mes_baixa', tmed, False),
                                        ('chuva_mes_alta', total, True), ('chuva_mes_baixa', total, False)):
                _melhor(alvo, campo, valor, ym, maior)
    anos = {}
    for ym in mensal:
        anos.setdefault(ym[:4], []).append(ym)
    ano_rows = []
    for ano in sorted(anos):
        if len(anos[ano]) == 12:
            tmed = sum(mensal[ym][0] for ym in anos[ano]) / 12
            chuva_ano = sum(mensal[ym][1] for ym in anos[ano])
            ano_rows.append({'rotulo': ano, 'tmed': tmed, 'chuva': chuva_ano})
            _melhor(geral, 'tmed_ano_alta', tmed, ano, True)
            _melhor(geral, 'tmed_ano_baixa', tmed, ano, False)
            _melhor(geral, 'chuva_ano_alta', chuva_ano, ano, True)
            _melhor(geral, 'chuva_ano_baixa', chuva_ano, ano, False)
    return {'geral': geral,
            'dia': [{'rotulo': k, **dia[k]} for k in sorted(dia)],
            'mes': [{'rotulo': k, **mes_rec[k]} for k in sorted(mes_rec)],
            'ano': ano_rows}


def recordes_do_periodo(db, eid, inicio='0000-00-00', fim='9999-12-31'):
    linhas = db.execute('SELECT data, maxima, minima, chuva, chuva_estimada, temperatura FROM dados '
                        'WHERE estacao_id = ? AND data BETWEEN ? AND ?', (eid, inicio, fim)).fetchall()
    return agrupar_recordes(linhas)


def main():
    if DESTINO.exists():
        if '--substituir' not in sys.argv:
            sys.exit(f'{DESTINO} já existe. Use --substituir para recriar.')
        DESTINO.unlink()
    origem = sqlite3.connect(ORIGEM.resolve().as_uri() + '?mode=ro', uri=True)
    fonte = sqlite3.connect(FONTE.resolve().as_uri() + '?mode=ro', uri=True)
    altitudes = dict(fonte.execute('SELECT id, altitude FROM estacoes'))
    destino = sqlite3.connect(DESTINO)
    destino.executescript(SCHEMA)
    cadastro = {r[0]: r for r in origem.execute('SELECT id, tipo, codigo, nome, latitude, longitude FROM estacoes')}
    consulta = origem.execute('''SELECT estacao_id, data, chuva, temperatura, MAX(chuva_estimada, temperatura_estimada)
        FROM dados WHERE chuva IS NOT NULL AND temperatura IS NOT NULL ORDER BY estacao_id, data''')
    total = 0
    for eid, linhas in groupby(consulta, key=lambda r: r[0]):
        com_janela = False
        for inicio, fim, dias, meses, chuva, temp, estimados, clima_c, clima_t, serie in janelas([(d, c, t, e) for _, d, c, t, e in linhas]):
            destino.execute('INSERT OR IGNORE INTO estacoes VALUES (?,?,?,?,?,?,?)', cadastro[eid] + (altitudes.get(eid),))
            kc = koppen(json.loads(clima_t), json.loads(clima_c))
            alt = koppen_alternativas(json.loads(clima_t), json.loads(clima_c))
            cur = destino.execute('INSERT INTO janelas (estacao_id, inicio, fim, dias, meses, chuva_mensal, temperatura_mensal, '
                                  'dias_estimados, clima_chuva, clima_temperatura, serie_anual, tendencia, koppen, koppen_alternativas) '
                                  'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                  (eid, inicio, fim, dias, meses, chuva, temp, estimados, clima_c, clima_t, serie,
                                   json.dumps(tendencia(json.loads(serie))), kc, json.dumps(alt)))
            destino.execute('INSERT INTO recordes (estacao_id, janela_id, grupos) VALUES (?,?,?)',
                            (eid, cur.lastrowid, json.dumps(recordes_do_periodo(origem, eid, inicio, fim))))
            com_janela = True
            total += 1
        if com_janela:
            destino.execute('INSERT INTO recordes (estacao_id, janela_id, grupos) VALUES (?,NULL,?)',
                            (eid, json.dumps(recordes_do_periodo(origem, eid))))
    destino.commit()
    print(f'{total} janelas em {destino.execute("SELECT count(*) FROM estacoes").fetchone()[0]} estações', flush=True)
    destino.close()
    origem.close()
    fonte.close()


if __name__ == '__main__':
    main()
