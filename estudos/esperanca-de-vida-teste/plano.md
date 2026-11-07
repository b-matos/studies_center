# Plano de estudo: Esperança de vida à nascença em Portugal (teste de pipeline)

> Nota: este é um estudo de teste da plataforma, usado para validar o pipeline `/estudo`
> de ponta a ponta. Não se destina a publicação como análise substantiva.

## Âmbito

- **Tema**: esperança de vida à nascença em Portugal, com comparação à União Europeia.
- **Âmbito temporal**: a série anual mais longa disponível em cada fonte (INE disponibiliza
  dados anuais desde, pelo menos, a década de 1970/1980; Eurostat disponibiliza séries
  comparáveis a partir de c. 1990/2002 dependendo do indicador). Usar o máximo de anos
  disponíveis em cada fonte, sem truncar artificialmente o início da série.
- **Âmbito geográfico**: Portugal (total e por sexo), com desagregação por NUTS II quando
  os dados o permitirem, e comparação com a média da União Europeia (UE-27 ou agregado
  disponível no Eurostat).

## Perguntas de investigação

1. Como evoluiu a esperança de vida à nascença em Portugal (total) desde o início da série
   disponível até ao ano mais recente?
   Eixo: esperança de vida. Fonte candidata: INE.

2. Qual é a diferença entre a esperança de vida à nascença de homens e mulheres em Portugal,
   e como essa diferença evoluiu ao longo do tempo?
   Eixo: esperança de vida. Fonte candidata: INE.

3. Como se compara a esperança de vida à nascença em Portugal com a média da União Europeia
   ao longo do tempo (convergência, divergência ou estabilidade)?
   Eixo: esperança de vida. Fonte candidata: Eurostat.

4. Existem diferenças na esperança de vida à nascença entre as regiões NUTS II de Portugal,
   e como evoluíram essas diferenças regionais?
   Eixo: esperança de vida. Fonte candidata: INE.

5. Houve alguma quebra, estagnação ou desaceleração visível na evolução da esperança de vida
   à nascença em Portugal (por exemplo, em torno de 2020, associada à pandemia de COVID-19),
   e como se compara essa quebra com o que se observou na média da UE?
   Eixo: esperança de vida. Fonte candidata: INE, Eurostat.

## Decisões em aberto

- Confirmar o ano de início efetivo das séries anuais no INE e no Eurostat (podem não
  coincidir); a fase de recolha de dados deve documentar o ano inicial real usado em cada
  fonte.
- Confirmar se o Eurostat disponibiliza esperança de vida à nascença desagregada por NUTS II
  para Portugal, ou se essa desagregação regional só está disponível no INE.
- Confirmar qual agregado da UE usar como referência de comparação (UE-27 atual vs.
  composição histórica da UE), dado que a composição da União Europeia mudou ao longo do
  tempo (ex.: Brexit).

## Exclusões de âmbito

- Não se inclui esperança de vida saudável (healthy life years) nem esperança de vida a
  outras idades (ex.: aos 65 anos) — o foco é exclusivamente a esperança de vida à nascença.
- Não se incluem causas de morte específicas nem decomposição por causa.
- Não se incluem comparações com países fora da União Europeia.
- Não se incluem projeções futuras de esperança de vida, apenas dados observados.
