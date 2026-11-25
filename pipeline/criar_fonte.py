"""Cria data/fonte.db a partir dos CSVs diários do INMET (estações convencionais e automáticas).

Entrada (somente leitura):
    data/raw/inmet/convencionais/*.csv   uma estação por arquivo, série diária
    data/raw/inmet/automaticas/*.csv     uma estação por arquivo, série diária

Saída:
    data/fonte.db, com as tabelas `estacoes` e `diario` (o mesmo esquema usado por preencher_ml.py).

Regras de leitura
-----------------
* Cada arquivo tem um cabeçalho de metadados ("Nome:", "Codigo Estacao:", "Latitude:", ...) seguido de
  uma linha "Data Medicao;..." com os nomes das colunas e, depois, uma linha por dia.
* Valores "null" viram NULL. Vírgula decimal é convertida para ponto.
* Alguns arquivos têm a linha "Data Medicao;" sem nomes de colunas. A ordem das colunas não é conhecida
  nesses casos: nos dados verificados, valores de temperatura aparecem na posição de precipitação. Por isso
  esses arquivos são PULADOS e listados na saída. (São 56 estações, sendo 54 automáticas e 2 convencionais.)
* Um arquivo sem a coluna de temperatura média (uma convencional) tem essa temperatura marcada como ausente.

Temperatura: o que é usado e por quê
------------------------------------
* Convencionais: "TEMPERATURA MEDIA COMPENSADA, DIARIA" é gravada em `temperatura_compensada_c`
  (metodo_temperatura = 'inmet_compensada'). É a média compensada fornecida pelo INMET.
* Automáticas: o arquivo traz apenas "TEMPERATURA MEDIA, DIARIA (AUT)". Ela é gravada na MESMA coluna,
  temperatura_compensada_c, com metodo_temperatura = 'media_diaria_aut'.
  ATENÇÃO: não é a média compensada. A compensada exige leituras horárias de 12 UTC e 24 UTC, que não
  estão mais disponíveis. Por isso, a série das automáticas usa a média diária como proxy. Isso precisa
  ser declarado em qualquer resultado que use a temperatura das automáticas.

Limitações
----------
* A data de fundação das automáticas não está nos CSVs diários. `fundacao_inmet` fica NULL, e o
  preenchimento usa apenas a primeira e a última observação de cada estação.
* `temperatura_12utc_c` e `temperatura_24utc_c` ficam NULL: vinham dos horários, que não são mais usados.

Uso (na raiz do projeto):
    python pipeline/criar_fonte.py              # cria fonte.db (recusa se já existir com dados)
    python pipeline/criar_fonte.py --substituir  # recria o fonte.db existente
"""
from pathlib import Path
import math
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw' / 'inmet'
DESTINO = ROOT / 'data' / 'fonte.db'

# Nomes de coluna esperados (normalizados: minúsculas, sem acentos e sem espaços extras).
# Campo do banco -> padrão regex do nome da coluna (já normalizado).
PADROES = {
    'precipitacao': r'^precipitacao total',
    'maxima': r'^temperatura maxima',
    'media': r'^temperatura media',
    'minima': r'^temperatura minima',
}

# Estações excluídas por erro de registro: a chuva é positiva em todos os dias com dado, sem nenhum
# dia seco em anos de série. Ex.: A707 registra ~20 mm todos os dias (média anual de ~7.000 mm).
EXCLUIDAS = {('automatica', 'A707'), ('automatica', 'A766')}

SCHEMA = """
CREATE TABLE estacoes (
  id INTEGER PRIMARY KEY, tipo TEXT NOT NULL, codigo TEXT NOT NULL,
  nome TEXT, latitude REAL, longitude REAL, altitude REAL, situacao TEXT,
  arquivo_diario TEXT NOT NULL, fundacao_inmet TEXT, fundacao_divergente INTEGER,
  UNIQUE(tipo, codigo));
CREATE TABLE diario (
  estacao_id INTEGER NOT NULL, data TEXT NOT NULL,
  precipitacao_mm REAL, temperatura_compensada_c REAL, temperatura_maxima_c REAL,
  temperatura_minima_c REAL, temperatura_12utc_c REAL, temperatura_24utc_c REAL,
  metodo_temperatura TEXT NOT NULL, PRIMARY KEY(estacao_id, data),
  FOREIGN KEY(estacao_id) REFERENCES estacoes(id));
"""


def normalizar(texto):
    """Minúsculas, sem acentos e com espaços simples, para comparar nomes de coluna."""
    trocas = str.maketrans('áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ', 'aaaaeeiooouc' + 'AAAAEEIOOOUC')
    return re.sub(r'\s+', ' ', texto.translate(trocas).lower()).strip()


def numero(texto):
    """Converte um valor do CSV. 'null' e vazio viram None; vírgula decimal vira ponto."""
    t = texto.strip()
    if t in ('', 'null', 'NULL'):
        return None
    try:
        v = float(t.replace(',', '.'))
    except ValueError:
        return None
    return None if math.isnan(v) else v


def ler_cabecalho(linhas):
    """Metadados da estação a partir das linhas antes de 'Data Medicao'."""
    meta = {}
    for linha in linhas:
        if linha.startswith('Data Medicao'):
            break
        if ':' in linha:
            chave, valor = linha.split(':', 1)
            meta[normalizar(chave)] = valor.strip()
    return meta


def mapear_colunas(cabecalho_dados):
    """Associa cada campo (precipitacao, maxima, media, minima) à posição da coluna no arquivo."""
    partes = [p.strip() for p in cabecalho_dados.split(';')][1:]  # a primeira é 'Data Medicao'
    partes = [p for p in partes if p]
    if not partes:
        return None  # cabeçalho sem nomes: a ordem das colunas não é conhecida
    mapa = {}
    for i, nome in enumerate(partes):
        n = normalizar(nome)
        for campo, padrao in PADROES.items():
            if re.match(padrao, n) and campo not in mapa:
                # Na automática, a média diária é "temperatura media, diaria (aut)"; a compensada não existe.
                mapa[campo] = i
    return mapa


def ler_arquivo(caminho):
    """Retorna (metadados da estação, linhas diárias) para um CSV do INMET."""
    try:
        texto = caminho.read_text(encoding='utf-8')
    except UnicodeDecodeError:          # alguns arquivos antigos podem vir em latin-1
        texto = caminho.read_text(encoding='latin-1')
    linhas = texto.splitlines()
    meta = ler_cabecalho(linhas)
    inicio = next((i for i, l in enumerate(linhas) if l.startswith('Data Medicao')), None)
    colunas = mapear_colunas(linhas[inicio]) if inicio is not None else None
    if colunas is None:
        return meta, None  # sinaliza arquivo pulado: sem cabeçalho de dados ou colunas desconhecidas
    dias = []
    for linha in linhas[inicio + 1:]:
        partes = linha.split(';')
        if not partes or not re.match(r'^\d{4}-\d{2}-\d{2}$', partes[0].strip()):
            continue
        data = partes[0].strip()
        def valor(campo):
            i = colunas.get(campo)
            return numero(partes[i + 1]) if i is not None and i + 1 < len(partes) else None
        dias.append((data, valor('precipitacao'), valor('maxima'), valor('media'), valor('minima')))
    return meta, dias


def gravar(con, tipo, arquivos):
    """Insere estações e dias. Retorna (estações gravadas, dias gravados)."""
    n_est = n_dia = 0
    for caminho in sorted(arquivos):
        meta, dias = ler_arquivo(caminho)
        codigo = meta.get('codigo estacao', caminho.stem.split('_')[1] if tipo == 'automatica' else caminho.stem.split('_')[0])
        if (tipo, codigo) in EXCLUIDAS:
            print(f'  EXCLUIDA (chuva sem nenhum dia seco, erro de registro): {codigo}', flush=True)
            continue
        if dias is None:
            print(f'  PULADO (sem cabeçalho de dados ou colunas sem nome): {caminho.name}', flush=True)
            continue
        if not dias:
            continue  # arquivo só com cabeçalho, sem nenhum dia
        cur = con.execute(
            'INSERT INTO estacoes (tipo, codigo, nome, latitude, longitude, altitude, situacao, arquivo_diario) VALUES (?,?,?,?,?,?,?,?)',
            (tipo, codigo, meta.get('nome'), numero(meta.get('latitude', '')), numero(meta.get('longitude', '')),
             numero(meta.get('altitude', '')), meta.get('situacao'), caminho.name))
        id_estacao = cur.lastrowid
        registros = []
        nome_metodo = 'inmet_compensada' if tipo == 'convencional' else 'media_diaria_aut'
        for data, precip, tmax, tmedia, tmin in dias:
            metodo = nome_metodo if tmedia is not None else 'ausente'
            registros.append((id_estacao, data, precip, tmedia, tmax, tmin, None, None, metodo))
        con.executemany('INSERT INTO diario VALUES (?,?,?,?,?,?,?,?,?)', registros)
        n_est += 1
        n_dia += len(registros)
    return n_est, n_dia


def main():
    if DESTINO.exists() and DESTINO.stat().st_size > 0 and '--substituir' not in sys.argv:
        sys.exit(f'{DESTINO} já existe. Use --substituir para recriar.')
    DESTINO.unlink(missing_ok=True)
    convencionais = list((RAW / 'convencionais').glob('*.csv'))
    automaticas = list((RAW / 'automaticas').glob('*.csv'))
    if not convencionais and not automaticas:
        sys.exit(f'Nenhum CSV encontrado em {RAW}.')
    con = sqlite3.connect(DESTINO)
    con.executescript(SCHEMA)
    print(f'Convencionais: {len(convencionais)} arquivos', flush=True)
    e1, d1 = gravar(con, 'convencional', convencionais)
    print(f'  {e1} estações, {d1} dias', flush=True)
    print(f'Automáticas: {len(automaticas)} arquivos', flush=True)
    e2, d2 = gravar(con, 'automatica', automaticas)
    print(f'  {e2} estações, {d2} dias', flush=True)
    con.commit()
    con.close()
    print(f'fonte.db criado: {e1 + e2} estações, {d1 + d2} dias.', flush=True)


if __name__ == '__main__':
    main()
