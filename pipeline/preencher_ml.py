"""Preenchimento de lacunas diárias por modelo (detalhes em pipeline/README.md).

Uso (na raiz do projeto):
    python pipeline/preencher_ml.py precipitacao
    python pipeline/preencher_ml.py temperatura

Entrada: data/fonte.db (somente leitura). Saída: data/preenchido.db.

Passos:
1. Para cada estação, os preditores são os valores dos vizinhos da mesma rede no dia,
   a média deles, os valores da própria estação um dia antes e depois, sazonalidade e local.
2. Um modelo por variável é treinado até 2014 com dias observados.
3. Cada estação é testada com lacunas artificiais em 2015-2019 e em 2020-2025.
   Só é preenchida se passar nos dois períodos.
"""
import json
import sqlite3
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

ROOT = Path(__file__).resolve().parents[1]
FONTE = ROOT / 'data' / 'fonte.db'
SAIDA = ROOT / 'data' / 'preenchido.db'
RELATORIOS = ROOT / 'data' / 'relatorios'

CONFIG = {
    'raio_km': 100.0,            # vizinhos da mesma rede até esta distância
    'k_vizinhos': 5,             # no máximo K vizinhos por estação
    'min_vizinhos_dia': 2,       # vizinhos com dado no dia exigidos para estimar
    'treino': ['1961-01-01', '2014-12-30'],
    'validacao': ['2015-01-01', '2019-12-31'],
    'teste': ['2020-01-01', '2025-12-31'],
    'max_amostra_treino': 1_500_000,
    'fracao_mascarada': 0.15,    # fração dos dias observados da janela que é mascarada
    'bloco_min': 1,
    'bloco_max': 30,
    'min_dias_avaliados': 100,   # dias mascarados com vizinhos suficientes para aprovar
    'ganho_minimo_rmse': 0.10,   # RMSE do modelo deve ser >=10% menor que a climatologia mensal
    'acerto_chuva_min': 0.70,    # só precipitação
    'vies_volume_max': 0.20,     # |viés no volume| máximo
    'seed': 20261112,
}

# variável -> (coluna em diario, nome do método gravado)
VARIAVEIS = {
    'precipitacao': ('precipitacao_mm', 'hgb_duas_etapas_chuva'),
    'temperatura': ('temperatura_compensada_c', 'hgb_regressao_temperatura'),
}


def carregar(coluna):
    """Matrizes dia x estação. Os extremos diários só são lidos para temperatura."""
    con = sqlite3.connect(FONTE)
    est = pd.read_sql('SELECT id, tipo, latitude, longitude, altitude, fundacao_inmet FROM estacoes', con)
    extra = ', temperatura_minima_c AS tmin, temperatura_maxima_c AS tmax' if coluna == 'temperatura_compensada_c' else ''
    d = pd.read_sql(f'SELECT estacao_id, data, {coluna} AS v{extra} FROM diario', con, parse_dates=['data'])
    con.close()
    datas = pd.date_range(d['data'].min(), d['data'].max(), freq='D')
    cols = est['id'].to_numpy()

    def matriz(campo):
        return d.pivot(index='data', columns='estacao_id', values=campo).reindex(index=datas, columns=cols).to_numpy(float)

    P = matriz('v')
    tmin = matriz('tmin') if extra else None
    tmax = matriz('tmax') if extra else None
    return est, datas, P, tmin, tmax


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def vizinhos(est, cfg):
    """Posição (na matriz) e distância dos vizinhos mais próximos da mesma rede, dentro do raio."""
    n, k = len(est), cfg['k_vizinhos']
    nb_pos = np.full((n, k), -1, dtype=int)
    nb_dist = np.full((n, k), np.nan)
    for tipo in est['tipo'].unique():
        pos = np.where((est['tipo'] == tipo) & est['latitude'].notna() & est['longitude'].notna())[0]
        if len(pos) < 2:
            continue
        lat, lon = est['latitude'].to_numpy()[pos], est['longitude'].to_numpy()[pos]
        D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
        np.fill_diagonal(D, np.inf)
        for i, p in enumerate(pos):
            slot = 0
            for j in np.argsort(D[i]):
                if slot == k or D[i, j] > cfg['raio_km']:
                    break
                nb_pos[p, slot], nb_dist[p, slot] = pos[j], D[i, j]
                slot += 1
    return nb_pos, nb_dist


def preditores(P, s, est, nb_pos, nb_dist, datas, own, variavel, cfg):
    """Uma linha por dia para a estação s. `own` é a série da própria estação (já mascarada, se for o caso)."""
    T, k = P.shape[0], cfg['k_vizinhos']
    N = np.full((T, k), np.nan)
    for j in range(k):
        if nb_pos[s, j] >= 0:
            N[:, j] = P[:, nb_pos[s, j]]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        n_disp = np.sum(~np.isnan(N), axis=1)
        media = np.where(n_disp > 0, np.nanmean(N, axis=1), np.nan)
    ant = lambda x: pd.Series(x).shift(1).to_numpy()
    pos = lambda x: pd.Series(x).shift(-1).to_numpy()

    cols = {f'nb{j}': N[:, j] for j in range(k)}
    cols['nb_n'] = n_disp.astype(float)
    cols['nb_media'] = media
    cols['nb_media_ant'] = ant(media)
    cols['nb_media_pos'] = pos(media)
    if variavel == 'precipitacao':
        cols['nb_frac_chuva'] = np.where(n_disp > 0, np.sum(N >= 1, axis=1) / np.maximum(n_disp, 1), np.nan)
    cols['own_ant'] = ant(own)
    cols['own_pos'] = pos(own)
    dist = nb_dist[s][np.isfinite(nb_dist[s])]
    cols['dist_media_vizinhos'] = np.full(T, dist.mean() if len(dist) else np.nan)
    doy = datas.day_of_year.to_numpy()
    cols['doy_sen'] = np.sin(2 * np.pi * doy / 365.25)
    cols['doy_cos'] = np.cos(2 * np.pi * doy / 365.25)
    cols['lat'] = np.full(T, est['latitude'].iloc[s])
    cols['lon'] = np.full(T, est['longitude'].iloc[s])
    cols['alt'] = np.full(T, est['altitude'].iloc[s])
    return pd.DataFrame(cols)


def novo_regressor(seed):
    return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, random_state=seed)


def treinar(P, est, nb_pos, nb_dist, datas, variavel, cfg):
    rng = np.random.default_rng(cfg['seed'])
    ini, fim = pd.Timestamp(cfg['treino'][0]), pd.Timestamp(cfg['treino'][1])
    jan = np.asarray((datas >= ini) & (datas <= fim))
    taxa = min(1.0, cfg['max_amostra_treino'] / max(int(np.sum(~np.isnan(P[jan]))), 1))
    Xs, ys = [], []
    for s in range(P.shape[1]):
        if np.isnan(est['latitude'].iloc[s]):
            continue
        X = preditores(P, s, est, nb_pos, nb_dist, datas, P[:, s], variavel, cfg)
        y = P[:, s]
        sel = jan & ~np.isnan(y) & (X['nb_n'].to_numpy() >= cfg['min_vizinhos_dia'])
        sel &= rng.random(len(y)) < taxa
        if sel.any():
            Xs.append(X[sel])
            ys.append(y[sel])
    X = pd.concat(Xs, ignore_index=True)
    y = np.concatenate(ys)
    print(f'  treino: {len(y)} linhas (taxa de amostragem {taxa:.3f})', flush=True)
    if variavel == 'precipitacao':
        clf = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=cfg['seed'])
        clf.fit(X, (y >= 1).astype(int))
        reg = novo_regressor(cfg['seed']).fit(X[y >= 1], y[y >= 1])
        return {'clf': clf, 'reg': reg}
    return {'reg': novo_regressor(cfg['seed']).fit(X, y)}


def prever(modelos, X, variavel):
    """Precipitação: P(chuva) x volume esperado. Temperatura: valor direto. Retorna (valor, prob_chuva)."""
    if variavel == 'precipitacao':
        p = modelos['clf'].predict_proba(X)[:, 1]
        return p * np.clip(modelos['reg'].predict(X), 0, None), p
    return modelos['reg'].predict(X), None


def mascarar(idx_obs, T, rng, cfg):
    """Blocos de dias observados mascarados até a fração configurada."""
    alvo = int(round(cfg['fracao_mascarada'] * len(idx_obs)))
    marcado = np.zeros(T, dtype=bool)
    obs = np.zeros(T, dtype=bool)
    obs[idx_obs] = True
    tentativas = 0
    while np.sum(marcado & obs) < alvo and tentativas < 100_000:
        tentativas += 1
        L = int(rng.integers(cfg['bloco_min'], cfg['bloco_max'] + 1))
        ini = int(rng.choice(idx_obs))
        fim = min(T, ini + L)
        marcado[ini:fim] |= obs[ini:fim]
    return marcado & obs


def clima_mensal(P, s, datas, cfg):
    """Média de cada mês do calendário no período de treino (base de comparação)."""
    ini, fim = pd.Timestamp(cfg['treino'][0]), pd.Timestamp(cfg['treino'][1])
    jan = np.asarray((datas >= ini) & (datas <= fim))
    serie = pd.Series(P[jan, s], index=datas[jan]).dropna()
    return serie.groupby(serie.index.month).mean().reindex(range(1, 13)).to_numpy()


def avaliar_periodo(P, s, est, nb_pos, nb_dist, datas, modelos, variavel, janela, clima, cfg, rng):
    ini, fim = pd.Timestamp(janela[0]), pd.Timestamp(janela[1])
    jan = np.asarray((datas >= ini) & (datas <= fim))
    idx_obs = np.where(jan & ~np.isnan(P[:, s]))[0]
    if len(idx_obs) < cfg['min_dias_avaliados'] * 2:
        return None
    marcado = mascarar(idx_obs, len(datas), rng, cfg)
    own = P[:, s].copy()
    own[marcado] = np.nan
    X = preditores(P, s, est, nb_pos, nb_dist, datas, own, variavel, cfg)
    sel = marcado & (X['nb_n'].to_numpy() >= cfg['min_vizinhos_dia'])
    if sel.sum() == 0:
        return None
    pred, p = prever(modelos, X[sel], variavel)
    obs = P[sel, s]
    base = clima[datas[sel].month.to_numpy() - 1]
    erro = pred - obs
    res = {
        'n_avaliados': int(sel.sum()),
        'mae': float(np.mean(np.abs(erro))),
        'rmse': float(np.sqrt(np.mean(erro ** 2))),
        'mae_clima': float(np.nanmean(np.abs(base - obs))),
        'rmse_clima': float(np.sqrt(np.nanmean((base - obs) ** 2))),
        'vies_volume': float((pred.sum() - obs.sum()) / obs.sum()) if obs.sum() > 0 else np.nan,
        'acerto_chuva': float(np.mean((p >= 0.5) == (obs >= 1))) if p is not None else np.nan,
    }
    return res


def decidir(res, variavel, cfg):
    """Retorna (aprovado, motivo) para um período."""
    if res is None:
        return False, 'sem_dias_avaliaveis'
    if res['n_avaliados'] < cfg['min_dias_avaliados']:
        return False, 'poucos_dias_avaliados'
    # Comparações escritas para que NaN reprove (ex.: estação sem dado antes de 2015 não tem climatologia).
    if not res['rmse'] <= (1 - cfg['ganho_minimo_rmse']) * res['rmse_clima']:
        return False, 'nao_supera_climatologia'
    if variavel == 'precipitacao':
        if not res['acerto_chuva'] >= cfg['acerto_chuva_min']:
            return False, 'acerto_chuva_baixo'
        if not abs(res['vies_volume']) <= cfg['vies_volume_max']:
            return False, 'vies_volume_alto'
    return True, 'aprovado'


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in VARIAVEIS:
        sys.exit('Uso: python pipeline/preencher_ml.py {precipitacao|temperatura}')
    variavel = sys.argv[1]
    coluna, metodo = VARIAVEIS[variavel]
    cfg = CONFIG
    rng = np.random.default_rng(cfg['seed'])

    print(f'Carregando {coluna}...', flush=True)
    est, datas, P, tmin, tmax = carregar(coluna)
    nb_pos, nb_dist = vizinhos(est, cfg)
    print(f'  {P.shape[1]} estações, {P.shape[0]} dias, {int(np.sum(~np.isnan(P)))} observações', flush=True)

    print('Treinando modelo...', flush=True)
    modelos = treinar(P, est, nb_pos, nb_dist, datas, variavel, cfg)

    print('Validando e testando por estação...', flush=True)
    registros, aprovadas = [], []
    for s in range(P.shape[1]):
        if np.isnan(est['latitude'].iloc[s]):
            continue
        clima = clima_mensal(P, s, datas, cfg)
        res_val = avaliar_periodo(P, s, est, nb_pos, nb_dist, datas, modelos, variavel, cfg['validacao'], clima, cfg, rng)
        res_teste = avaliar_periodo(P, s, est, nb_pos, nb_dist, datas, modelos, variavel, cfg['teste'], clima, cfg, rng)
        ok_val, motivo_val = decidir(res_val, variavel, cfg)
        ok_teste, motivo_teste = decidir(res_teste, variavel, cfg)
        aprovado = ok_val and ok_teste
        if aprovado:
            aprovadas.append(s)
        motivo = motivo_val if not ok_val else ('aprovado' if ok_teste else 'falhou_teste_' + motivo_teste)
        for periodo, res in (('validacao', res_val), ('teste', res_teste)):
            registros.append({'estacao_id': int(est['id'].iloc[s]), 'variavel': coluna, 'periodo': periodo,
                              **(res or {}), 'aprovado': int(aprovado), 'motivo': motivo})
    val = pd.DataFrame(registros)
    print(f'  estações aprovadas (validação e teste): {len(aprovadas)} de {val.estacao_id.nunique()}', flush=True)

    print('Preenchendo lacunas das estações aprovadas...', flush=True)
    saidas = []
    for s in aprovadas:
        obs = ~np.isnan(P[:, s])
        if not obs.any():
            continue
        X = preditores(P, s, est, nb_pos, nb_dist, datas, P[:, s], variavel, cfg)
        # Só dentro da operação: entre a primeira e a última observação (e após a fundação, se conhecida).
        primeiro, ultimo = np.where(obs)[0][[0, -1]]
        alvo = np.zeros(len(datas), dtype=bool)
        alvo[primeiro:ultimo + 1] = True
        # Só lacunas de até bloco_max dias seguidos: é o tamanho testado na validação. Lacunas maiores ficam vazias.
        buraco = pd.Series(~obs)
        tamanho = buraco.groupby((buraco != buraco.shift()).cumsum()).transform('size').to_numpy()
        alvo &= ~obs & (tamanho <= cfg['bloco_max']) & (X['nb_n'].to_numpy() >= cfg['min_vizinhos_dia'])
        fund = est['fundacao_inmet'].iloc[s]
        if est['tipo'].iloc[s] == 'automatica' and pd.notna(fund):
            alvo &= datas >= pd.Timestamp(fund)
        if not alvo.any():
            continue
        valor, prob = prever(modelos, X[alvo], variavel)
        df = pd.DataFrame({
            'estacao_id': int(est['id'].iloc[s]),
            'data': datas[alvo].strftime('%Y-%m-%d'),
            'variavel': coluna,
            'valor': valor,
            'prob_chuva': prob if prob is not None else np.nan,
            'n_vizinhos': X.loc[alvo, 'nb_n'].astype(int).to_numpy(),
            'metodo': metodo,
        })
        if variavel == 'temperatura':
            pos = np.where(alvo)[0]
            mn, mx = tmin[pos, s], tmax[pos, s]
            df['fora_extremos'] = (((~np.isnan(mn)) & (valor < mn)) | ((~np.isnan(mx)) & (valor > mx))).astype(int)
        saidas.append(df)
    final = pd.concat(saidas, ignore_index=True) if saidas else pd.DataFrame()
    print(f'  estimativas geradas: {len(final)}', flush=True)

    print('Gravando preenchido.db...', flush=True)
    con = sqlite3.connect(SAIDA)
    con.executescript('''
        CREATE TABLE IF NOT EXISTS estimativas_ml (estacao_id INTEGER NOT NULL, data TEXT NOT NULL,
            variavel TEXT NOT NULL, valor REAL NOT NULL, prob_chuva REAL, n_vizinhos INTEGER NOT NULL,
            metodo TEXT NOT NULL, fora_extremos INTEGER, PRIMARY KEY(estacao_id,data,variavel));
        CREATE TABLE IF NOT EXISTS validacao_ml (estacao_id INTEGER NOT NULL, variavel TEXT NOT NULL,
            periodo TEXT NOT NULL, n_avaliados INTEGER, mae REAL, rmse REAL, mae_clima REAL, rmse_clima REAL,
            acerto_chuva REAL, vies_volume REAL, aprovado INTEGER, motivo TEXT, PRIMARY KEY(estacao_id,variavel,periodo));
        CREATE TABLE IF NOT EXISTS configuracao_ml (variavel TEXT NOT NULL, chave TEXT NOT NULL, valor TEXT,
            PRIMARY KEY(variavel,chave));''')
    for tabela in ('estimativas_ml', 'validacao_ml', 'configuracao_ml'):
        con.execute(f'DELETE FROM {tabela} WHERE variavel=?', (coluna,))
    if len(final):
        final.to_sql('estimativas_ml', con, if_exists='append', index=False)
    val.to_sql('validacao_ml', con, if_exists='append', index=False)
    con.executemany('INSERT INTO configuracao_ml VALUES (?,?,?)',
                    [(coluna, k, json.dumps(v)) for k, v in cfg.items()] + [(coluna, 'modelo', metodo)])
    con.commit()
    con.close()

    RELATORIOS.mkdir(parents=True, exist_ok=True)
    val.to_csv(RELATORIOS / f'ml_validacao_{variavel}.csv', sep=';', index=False, encoding='utf-8-sig')
    print('Concluído.', flush=True)


if __name__ == '__main__':
    main()
