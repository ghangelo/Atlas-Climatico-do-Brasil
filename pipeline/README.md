# Preenchimento de lacunas por aprendizado de máquina

## Bancos

| Arquivo | Conteúdo | Alteração |
| --- | --- | --- |
| `data/fonte.db` | Tabelas `estacoes` e `diario`, a partir dos CSVs em `data/raw/inmet/` | Criado por `criar_fonte.py`; não é editado depois |
| `data/preenchido.db` | `estimativas_ml`, `validacao_ml`, `configuracao_ml` | Gerado por `preencher_ml.py`, uma variável por vez |

## Execução

Na raiz do projeto:

```bash
python pipeline/criar_fonte.py
python pipeline/preencher_ml.py precipitacao
python pipeline/preencher_ml.py temperatura
python -m pipeline.preparar_dados
```

`preparar_dados` gera `data/combinado.db` (série diária com os valores observados e as estimativas aceitas, e a tabela mensal). `janelas_completas` gera `data/atlas.db` a partir dele.

`criar_fonte.py` recusa sobrescrever `fonte.db`; use `--substituir` para recriá-lo. Cada execução de `preencher_ml.py` substitui só as linhas da própria variável. Os parâmetros ficam em `CONFIG`, no início do script, e são gravados em `configuracao_ml`.

Temperatura: nas automáticas, o CSV traz só a média diária (AUT), não a média compensada. Essa média é gravada na mesma coluna, com `metodo_temperatura = 'media_diaria_aut'`.

## Método

1. **Vizinhos.** Até 5 estações da mesma rede (`tipo`) a no máximo 100 km.
2. **Preditores para cada dia t da estação s.** Valor de cada vizinho em t; número de vizinhos com dado; média dos vizinhos em t, t-1 e t+1; fração de vizinhos com chuva (só precipitação); valor da própria estação em t-1 e t+1; seno e cosseno do dia do ano; latitude, longitude e altitude. O valor de s em t nunca é preditor.
3. **Modelo.** `HistGradientBoosting` do scikit-learn, um modelo global por variável, treinado com dados de 1961 a 2014-12-30.
   - Precipitação em duas etapas: classificador de chuva (≥ 1 mm) × regressor de volume em dias chuvosos. A estimativa é `P(chuva) × volume esperado`.
   - Temperatura: regressor direto.
4. **Períodos.** Treino até 2014-12-30; validação 2015–2019; teste 2020–2025.
5. **Validação por estação.** Dias observados são mascarados em blocos de 1 a 30 dias, cerca de 15% do total. O erro é medido nesses dias e comparado com a climatologia mensal do treino.
6. **Critérios de aprovação** (ver `CONFIG`). Uma estação é aprovada só se passar nos critérios na validação **e** no teste:
   - pelo menos 100 dias mascarados com ao menos 2 vizinhos;
   - RMSE do modelo ao menos 10% menor que o da climatologia;
   - precipitação: acerto de chuva ≥ 70% e |viés de volume| ≤ 20%.
7. **Preenchimento.** Só nas estações aprovadas, só entre a primeira e a última observação (a data de fundação não está nos CSVs diários), e só onde a lacuna tem ≥ 2 vizinhos com dado no dia.
   - **Tamanho da lacuna:** só entram lacunas de até 30 dias seguidos, que é o tamanho testado na validação. Lacunas maiores ficam sem estimativa. Antes dessa regra, cerca de dois terços dos dias estimados estavam em blocos de mais de 30 dias, sem validação.
8. **Temperatura fora dos extremos.** Estimativas abaixo da mínima ou acima da máxima diárias do próprio banco são gravadas com `fora_extremos = 1`. Não devem ser usadas como valor final sem revisão.

## Resultado da última execução

| Variável | Estações aprovadas (de 1.219) | Estimativas geradas | Fora dos extremos |
| --- | --- | --- | --- |
| Precipitação | 72 | 10.313 | — |
| Temperatura | 158 | 20.498 | 289 |

A cobertura é baixa porque a maioria das estações não passa nos critérios. O banco guarda só as estações aprovadas; quantas passaram só na validação não fica registrado.

## Limites

- O teste deixa de ser cego, porque a aprovação exige também o desempenho no período de teste. O desempenho das estações aprovadas é, portanto, otimista. Uma validação independente exige dados novos (por exemplo, 2026).
- A temperatura das automáticas é a média diária (AUT), não a compensada. O Atlas avisa isso no popup.
- A equivalência entre redes convencional e automática não foi demonstrada.
- As estimativas são provisórias e trazem uma flag em cada linha. Não são medições.
- Relatórios: `data/relatorios/ml_validacao_precipitacao.csv` e `ml_validacao_temperatura.csv`.
