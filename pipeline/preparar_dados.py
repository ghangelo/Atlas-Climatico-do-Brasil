"""Cria data/combinado.db a partir de data/fonte.db e data/preenchido.db.

Uso (na raiz do projeto):
    python -m pipeline.preparar_dados               # cria combinado.db (recusa se já existir)
    python -m pipeline.preparar_dados --substituir  # apaga o combinado.db atual e recria

As origens são abertas apenas para leitura. O combinado.db contém:
- dados: dia a dia, com valor original quando existe e estimativa do modelo (preenchido.db) caso contrário.
  Temperaturas estimadas fora dos extremos diários do próprio banco são omitidas.
- mensal: agregação mensal para Köppen. Total/média só existem quando o mês tem todos os dias.
"""
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
FONTE = ROOT / 'data' / 'fonte.db'
PREENCHIDO = ROOT / 'data' / 'preenchido.db'
DESTINO = ROOT / 'data' / 'combinado.db'


def construir(c):
    c.execute('ATTACH DATABASE ? AS fonte', (str(FONTE),))
    c.execute('ATTACH DATABASE ? AS preenchido', (str(PREENCHIDO),))
    print('Estações', flush=True)
    c.execute('''CREATE TABLE estacoes AS SELECT id,tipo,codigo,nome,latitude,longitude FROM fonte.estacoes
        WHERE latitude BETWEEN -34 AND 6 AND longitude BETWEEN -74 AND -28''')
    c.execute('CREATE UNIQUE INDEX estacoes_id ON estacoes(id)')
    print('Dados diários', flush=True)
    c.execute('''CREATE TABLE dados AS SELECT d.estacao_id, d.data,
        COALESCE(d.precipitacao_mm, pe.valor) AS chuva,
        CASE WHEN d.precipitacao_mm IS NULL AND pe.valor IS NOT NULL THEN 1 ELSE 0 END AS chuva_estimada,
        COALESCE(d.temperatura_compensada_c, te.valor) AS temperatura,
        CASE WHEN d.temperatura_compensada_c IS NULL AND te.valor IS NOT NULL THEN 1 ELSE 0 END AS temperatura_estimada,
        d.temperatura_minima_c AS minima, d.temperatura_maxima_c AS maxima
        FROM fonte.diario d
        JOIN estacoes e ON e.id = d.estacao_id
        LEFT JOIN preenchido.estimativas_ml pe ON pe.estacao_id = d.estacao_id AND pe.data = d.data AND pe.variavel = 'precipitacao_mm'
        LEFT JOIN preenchido.estimativas_ml te ON te.estacao_id = d.estacao_id AND te.data = d.data
             AND te.variavel = 'temperatura_compensada_c' AND te.fora_extremos = 0
        WHERE COALESCE(d.precipitacao_mm, pe.valor) IS NOT NULL
           OR COALESCE(d.temperatura_compensada_c, te.valor) IS NOT NULL
           OR d.temperatura_minima_c IS NOT NULL OR d.temperatura_maxima_c IS NOT NULL''')
    c.execute('CREATE INDEX dados_estacao_data ON dados(estacao_id, data)')
    c.commit()
    print('Mensal', flush=True)
    # Um mês só tem total/média quando todos os dias do calendário têm valor.
    c.execute('''CREATE TABLE mensal AS SELECT estacao_id, mes, dias_calendario,
        dias_chuva, dias_temperatura, dias_chuva_estimados, dias_temperatura_estimados,
        CASE WHEN dias_chuva = dias_calendario THEN soma_chuva END AS precipitacao_total_mm,
        CASE WHEN dias_temperatura = dias_calendario THEN media_temperatura END AS temperatura_media_c,
        CASE WHEN dias_chuva_estimados > 0 THEN 1 ELSE 0 END AS chuva_mensal_estimada,
        CASE WHEN dias_temperatura_estimados > 0 THEN 1 ELSE 0 END AS temperatura_mensal_estimada
        FROM (SELECT estacao_id, substr(data,1,7) AS mes,
            CAST(strftime('%d', date(substr(data,1,7) || '-01', '+1 month', '-1 day')) AS INTEGER) AS dias_calendario,
            COUNT(chuva) AS dias_chuva, COUNT(temperatura) AS dias_temperatura,
            SUM(chuva_estimada) AS dias_chuva_estimados, SUM(temperatura_estimada) AS dias_temperatura_estimados,
            SUM(chuva) AS soma_chuva, AVG(temperatura) AS media_temperatura
          FROM dados GROUP BY estacao_id, substr(data,1,7))''')
    c.execute('CREATE UNIQUE INDEX mensal_chave ON mensal(estacao_id, mes)')
    c.commit()
    c.execute('DETACH DATABASE fonte')
    c.execute('DETACH DATABASE preenchido')


def main():
    substituir = '--substituir' in sys.argv
    for path in (FONTE, PREENCHIDO):
        if not path.exists():
            raise SystemExit(f'{path.name} não encontrado. Execute pipeline/criar_fonte.py e pipeline/preencher_ml.py.')
    if DESTINO.exists():
        if not substituir:
            raise SystemExit('O banco combinado já existe; use --substituir para recriá-lo.')
        DESTINO.unlink()
    c = sqlite3.connect(DESTINO)
    try:
        construir(c)
        print('Dados', c.execute('SELECT count(*), min(data), max(data) FROM dados').fetchone(), flush=True)
        print('Estimativas de chuva', c.execute('SELECT sum(chuva_estimada) FROM dados').fetchone()[0], flush=True)
        print('Estimativas de temperatura', c.execute('SELECT sum(temperatura_estimada) FROM dados').fetchone()[0], flush=True)
        print('Integridade', c.execute('PRAGMA quick_check').fetchone()[0], flush=True)
    except Exception:
        c.close()
        DESTINO.unlink(missing_ok=True)
        raise
    c.close()
    print('CONCLUIDO', flush=True)


if __name__ == '__main__':
    main()
