# Histórico de versões

## 0.1.2 — 23 de setembro de 2026

- Adicionado o menu de gerenciamento ao lado de cada fonte cadastrada.
- Nova opção **Desconectar fonte**, preservando índice, favoritos, tags, notas e coleções.
- Nova opção **Remover do catálogo**, eliminando registros e miniaturas sem alterar os arquivos originais.
- A remoção do catálogo exige confirmação explícita e fica bloqueada durante uma indexação ativa.
- Fontes desconectadas podem ser recuperadas adicionando novamente o mesmo caminho.

## 0.1.1 — 22 de setembro de 2026

- Corrigidas as quebras de linha dos arquivos `.bat` para o padrão CRLF do Windows.
- O instalador, o inicializador e o atalho para os dados agora são interpretados corretamente pelo `cmd.exe`.
- Adicionado um teste automático para impedir que o problema reapareça em pacotes futuros.

## 0.1.0 — 22 de setembro de 2026

- Primeira versão funcional do DTIA Local.
- Indexação incremental de múltiplas pastas e HDs.
- Banco SQLite e miniaturas locais sem cópia dos originais.
- Navegação, pesquisa, filtros, favoritos, tags, notas e coleções.
- Leitura de dimensões e EXIF essencial.
- Detecção de arquivos exatamente duplicados por SHA-256.
- Persistência de unidades externas desconectadas como fontes offline.
- Classificação Geral, Sensível e Adulto/NSFW.
- Controles para exibir, desfocar ou ocultar conteúdo privado.
- Acesso restrito ao próprio computador por padrão.
