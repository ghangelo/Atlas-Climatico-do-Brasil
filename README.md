# Atlas Climático — séries completas

Projeto local para estimar lacunas em séries diárias do INMET e mostrar as estações com trechos longos e completos de dados. Usa Python, SQLite, NumPy e JavaScript simples, sem framework nem compilação.

## Usar o Atlas

Na raiz do projeto:

```bash
python -m atlas.app
```

Acesse http://127.0.0.1:8001/.

O site lê arquivos JSON em `atlas/static/api/`, gerados por `python -m pipeline.exportar_site` a partir do `atlas.db`. Por isso ele também funciona sem servidor, no GitHub Pages: o workflow `.github/workflows/pages.yml` publica `atlas/static` a cada push na `main`. Depois de recriar o `atlas.db`, rode o exportador e envie os JSON novos. O mapa (MapLibre) e os fundos (OpenFreeMap e Esri, sem chave de API) precisam de internet.

O Atlas mostra trechos de pelo menos 10 anos seguidos em que a estação tem precipitação e temperatura juntas, com dados observados e estimados pelo modelo (lacunas de até 30 dias). Uma estação pode ter mais de um trecho. Cada trecho mostra a parcela de dias estimados, o total mensal médio de chuva e a média mensal de temperatura. Estações com só uma das variáveis não entram.

O banco `data/atlas.db` é gerado por `python -m pipeline.janelas_completas`.

## Verificar

```bash
python -m unittest discover -s tests -t .
```

## Onde encontrar cada parte

| Caminho | Finalidade |
| --- | --- |
| `atlas/` | Servidor do Atlas (`app.py`) e a página em `static/` |
| `pipeline/` | Criação de `fonte.db`, preenchimento de lacunas por modelo (método em [pipeline/README.md](pipeline/README.md)), `combinado.db`, `atlas.db` |
| `tests/` | Testes Python |
| `data/raw/inmet/` | Arquivos originais do INMET (CSV) |
| `data/fonte.db` | Dados diários originais (`estacoes`, `diario`); não é alterado depois de criado |
| `data/preenchido.db` | Estimativas do modelo, validação por estação e configuração |
| `data/combinado.db` | Série diária com valores observados e estimativas aceitas, e tabela mensal |
| `data/atlas.db` | Trechos de 10 anos ou mais usados pelo Atlas |
| `data/relatorios/` | Relatórios de validação do preenchimento |
| `arquivo_morto/` | Código e relatórios que o site não usa mais (validação da interpolação espacial) e uma imagem sem uso |
| `docs/ARQUITETURA.md` | Fluxo de dados e endpoints |
| `docs/bibliografia/` | PDFs de referência (Peel et al., 2007; Beck et al., 2023) |
| `docs/proposta-gabriel-henrique-angelo-ftl.pdf` | Proposta do projeto |

## Metodologia e limites

- Método de preenchimento e critérios de aprovação: [pipeline/README.md](pipeline/README.md).
- Nulos não são zeros. Dias estimados aparecem como parcela de cada trecho.
- O preenchimento de lacunas usou 2020–2025 para aprovar as estações, portanto esse período não serve mais como teste independente.

## Reprodução

Na raiz do projeto, nesta ordem:

1. `python pipeline/criar_fonte.py` cria `data/fonte.db` a partir de `data/raw/inmet/`.
2. `python pipeline/preencher_ml.py precipitacao` e `python pipeline/preencher_ml.py temperatura` geram `data/preenchido.db`.
3. `python -m pipeline.preparar_dados` gera `data/combinado.db` (use `--substituir` para recriar).
4. `python -m pipeline.janelas_completas` gera `data/atlas.db` (use `--substituir` para recriar).

## Desenvolvimento

Python 3 com NumPy, pandas e scikit-learn (versões em `requirements-processamento.txt`).
