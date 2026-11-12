# Metodologia

Tudo no Dash FIDCs vem de dados abertos e gratuitos da CVM, baixados automaticamente todos os dias. Nada é digitado à mão.

## Fontes

- **Informe Mensal FIDC** (`dados.cvm.gov.br/dados/FIDC/DOC/INF_MENSAL/DADOS/`): um arquivo por competência. Cada FIDC (ou classe de cotas, depois da RCVM 175) entrega o informe até cerca do dia 15 do mês seguinte, e a CVM republica o arquivo quando chegam correções. O app lê os últimos 24 meses e confere os 3 mais recentes todo dia.
- **Cadastro de fundos e classes** (`dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip`): gestor, administrador, custodiante, auditor, situação, data de constituição, adaptação à RCVM 175, público-alvo e o PL mais recente do cadastro.

O cruzamento entre o informe e o cadastro é feito pelo CNPJ da classe (ou do fundo, antes da RCVM 175), sem depender do nome.

## Competência mais recente

É o mês mais novo com pelo menos metade dos fundos do mês anterior. Enquanto os fundos ainda estão entregando o informe de um mês, o painel continua mostrando o mês completo anterior, para o mercado não parecer menor do que é.

## FIC-FIDC

Um fundo é tratado como FIC-FIDC quando pelo menos metade da carteira é de cotas de outros FIDCs (Tabela I, itens 2h e 2i do informe). Somas de PL e de captação deixam os FIC-FIDCs de fora para não contar o mesmo dinheiro duas vezes. Eles continuam na lista e nas contagens de fundos.

## Segmento

Tabela II do informe: valor dos direitos creditórios por segmento. O segmento do fundo é o de maior valor; o subsegmento é a maior linha dentro dele (por exemplo, Financeiro → Crédito consignado). O peso mostra quanto da carteira por segmento está no maior. Fundos sem carteira por segmento (em geral FIC-FIDCs, ou fundos no início ou no fim da vida) aparecem como “Sem direitos creditórios por segmento”.

## Inadimplência e PDD

- **Inadimplência** = direitos creditórios vencidos e não pagos ÷ (a vencer + inadimplentes), somando as Tabelas V (com aquisição substancial de riscos) e VI (sem).
- **Inadimplência acima de 90 dias** = parcelas inadimplentes há mais de 90 dias (faixas 91–120 em diante).
- **Inadimplência do mercado** (Início) = soma dos inadimplentes ÷ soma da base de todos os fundos, sem FIC-FIDC. A mediana por fundo aparece ao lado.
- **PDD / DC** = redução ao valor recuperável (Tabela I, itens 2a11 e 2b11) ÷ direitos creditórios.

## Subordinação

Valor de cada série = quantidade de cotas × valor da cota (Tabela X.2). Subordinação = (subordinadas + mezanino) ÷ valor total das cotas. Valores fora de 0% a 100% são descartados.

## Rentabilidade

Rentabilidade no mês da série sênior de maior valor e da subordinada de maior valor (Tabela X.3). O informe traz a rentabilidade em percentual; valores acima de 100% no mês, que são erros de preenchimento, são descartados.

## Cotistas e alocador

- **Cotistas** = soma do número de cotistas de todas as séries (Tabela X.1).
- **Alocador** = tipo de cotista com mais da metade dos cotistas do fundo (Tabela X.1.1, sênior e subordinadas somadas): pessoa física, outros fundos de investimento, banco, fundo de pensão (EFPC), RPPS etc. Quando nenhum tipo passa de 50%, aparece “Misto”. O informe conta pessoas, não dinheiro, e não traz o nome de quem investe.

## Cedentes

Tabela I, itens 2a12 e 2b12: até nove maiores cedentes por fundo, com o peso de cada um. Só CNPJs válidos de empresas são guardados; CPFs são descartados ao ler o arquivo. Pesos acima de 100% são descartados. O nome do cedente aparece quando o CNPJ consta no cadastro da CVM (fundos, gestoras, administradores); para os demais, só o CNPJ. Cerca de um terço dos fundos preenche este campo.

## Captação líquida

Captações − resgates − amortizações do mês (Tabela X.4).

## Liquidez, prazo e rating

- **Liquidez** (Tabela X.5): ativos que viram caixa em até 0, 30, 60, 90, 180, 360 dias ou mais.
- **Prazo de vencimento** (Tabelas V e VI): direitos creditórios a vencer por faixa de dias.
- **Rating SCR** (Tabela X): valor por classificação de risco do devedor (AA a H).

## Limites conhecidos

- A CVM não informa quem são os cotistas nem o nome dos cedentes; o painel mostra o que os arquivos trazem.
- Os rótulos dos segmentos G (“Cartão de crédito”) e H (“Factoring”) seguem o leiaute do informe; vale conferir no dicionário de dados da CVM (pasta META) se algum rótulo parecer estranho.
- Os endereços dos arquivos da CVM não puderam ser testados do ambiente onde o código foi escrito; a página Status dos dados mostra se algum download falhar.
