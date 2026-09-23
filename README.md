# DataTech Image Archives — Local

O DTIA Local cataloga imagens diretamente das pastas, SSDs e HDs do computador. Os arquivos originais permanecem exatamente onde estão: o aplicativo guarda apenas um banco de metadados e miniaturas para navegação rápida.

## Instalação no Windows 11

1. Extraia todo o conteúdo do arquivo ZIP para uma pasta fixa, por exemplo `C:\DataTech\DTIA Local`.
2. Execute `INSTALAR.bat` uma única vez.
3. Depois da instalação, execute `INICIAR.bat` sempre que quiser usar o arquivo.
4. O DTIA abrirá no navegador em `http://127.0.0.1:8148`.

Se o Python 3 não estiver instalado, o instalador oferecerá a instalação pelo `winget`. O ambiente Python criado dentro da pasta do programa é isolado dos demais projetos do computador.

## Primeiro uso

1. Clique em **Adicionar pasta**.
2. Escolha uma pasta de imagens ou a raiz de um HD externo.
3. Aguarde a primeira indexação. Ela pode demorar em um acervo grande porque o DTIA lê cada imagem, cria uma miniatura e calcula uma assinatura para detectar cópias exatas.
4. Depois disso, novas varreduras são incrementais: arquivos que não mudaram são reconhecidos e ignorados rapidamente.

Você pode adicionar várias pastas e unidades. Se um HD externo estiver desconectado, seu catálogo continua visível como **offline**; ao reconectar o disco e reindexar, os arquivos voltam a ficar disponíveis.

## O que esta versão faz

- Cataloga JPG/JPEG, PNG, WebP, GIF, BMP, TIFF, AVIF e, quando os codecs do sistema permitirem, HEIC/HEIF.
- Mantém os originais nas pastas existentes; não move, renomeia, edita ou apaga imagens.
- Gera miniaturas locais e lê dimensões, formato, tamanho, cor média e metadados EXIF essenciais.
- Pesquisa por nome, caminho, título, nota e tag.
- Filtra por pasta/HD, orientação, formato, classificação e resolução mínima.
- Organiza favoritos, tags, notas e coleções sem alterar a estrutura de pastas.
- Detecta cópias byte a byte idênticas, mesmo com nomes diferentes.
- Marca imagens como **Geral**, **Sensível** ou **Adulto / NSFW**.
- Pode exibir, desfocar ou ocultar conteúdo sensível e adulto.
- Continua mostrando no catálogo os arquivos de unidades temporariamente desconectadas.
- Permite desconectar uma fonte preservando sua organização ou removê-la completamente do catálogo sem apagar os originais.

## Privacidade

O servidor do DTIA aceita conexões apenas do próprio computador (`127.0.0.1`). Não há upload automático, telemetria ou sincronização com nuvem. Conteúdo NSFW é permitido no arquivo local, desde que seja legal e consensual e envolva exclusivamente adultos.

As classificações são manuais nesta versão: o DTIA não envia imagens a um classificador externo. Por padrão, itens marcados como adultos aparecem desfocados até serem revelados durante a sessão.

## Onde ficam os dados

No Windows, o índice e as miniaturas ficam em:

`%LOCALAPPDATA%\DTIA Local`

Esse diretório contém:

- `dtia-local.sqlite3`: banco com pastas, metadados, tags, favoritos e coleções;
- `thumbnails`: miniaturas geradas pelo aplicativo.

Para fazer backup, feche o DTIA e copie essa pasta. Os originais continuam nos seus próprios discos e devem seguir sua rotina normal de backup.

## Uso diário

- **Reindexar** procura arquivos novos, alterados ou removidos em todas as fontes conectadas.
- **Localizar** abre o Explorador de Arquivos com o original selecionado.
- **Original** abre a imagem original no navegador, sem criar uma cópia.
- **Duplicatas exatas** mostra arquivos com a mesma assinatura SHA-256. Revise-os manualmente; esta versão nunca apaga duplicatas.
- **Privacidade** controla a exibição de material sensível e adulto.
- O botão **•••** ao lado de cada fonte abre as opções **Desconectar fonte** e **Remover do catálogo**.
- **Desconectar fonte** preserva metadados e miniaturas; adicionar novamente o mesmo caminho restaura a fonte.
- **Remover do catálogo** elimina apenas registros e miniaturas do DTIA. Os arquivos originais permanecem no HD.

## Encerramento

O DTIA roda enquanto a janela preta iniciada por `INICIAR.bat` estiver aberta. Você pode minimizá-la. Para encerrar completamente, feche essa janela ou pressione `Ctrl+C` nela.

## Solução de problemas

- **A pasta não abre no seletor:** use “Informar o caminho manualmente” na tela inicial, como `D:\Imagens`.
- **Um HD aparece offline:** conecte-o com a mesma letra de unidade usada originalmente e clique em **Reindexar**.
- **HEIC/AVIF aparece com erro:** o suporte depende dos codecs disponíveis para o Pillow/Windows. O item continua registrado para diagnóstico.
- **A interface não abre:** mantenha a janela do DTIA aberta e visite manualmente `http://127.0.0.1:8148` no Edge ou Chrome.
- **A instalação falha:** confirme que o computador está conectado à internet e execute novamente `INSTALAR.bat`.

## Escopo da versão 0.1.2

Esta é a primeira versão local funcional. O índice já armazena uma assinatura perceptual por imagem para permitir, numa evolução futura, localizar imagens visualmente semelhantes, variações de resolução e recortes. Nesta versão, a tela de duplicatas mostra apenas equivalências exatas, evitando falsos positivos.
