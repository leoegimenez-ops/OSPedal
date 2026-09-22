# EQ y compresores: alternativas abiertas a plugins comerciales

Mismo principio que en `docs/capturas-neuronales.md`, aplicado a plugins de EQ y dinámica en vez
de a modelos neuronales: **FabFilter (Pro-Q y similares) es software comercial cerrado**, no se
puede portar ni clonar su algoritmo para este proyecto. Pero el ecosistema LV2 de Linux tiene
suites de altísima calidad, GPL/LGPL, que Guitarix ya carga sin necesidad de nada adicional.

## Tres suites verificadas

| Proyecto | Qué tiene | Licencia |
|---|---|---|
| **[LSP Plugins](https://lsp-plug.in/)** | Parametric Equalizer (hasta 16 bandas, con inspección de filtro para buscar resonancias), Compressor, Multiband Compressor, GOTT Compressor | LGPL/GPL |
| **[x42-plugins](https://github.com/x42) (Robin Gareus)** | `fil4.lv2` — EQ paramétrico de 4 bandas con display de espectro y waterfall FFT en vivo; `darc.lv2` — compresor de propósito general | GPL |
| **[Calf Studio Gear](https://github.com/calf-studio-gear/calf)** | Compressor, Sidechain Compressor, Multiband Compressor, Equalizer de 5/8/12/30 bandas | GPL/LGPL |

Los tres están empaquetados en Debian (`apt install lsp-plugins-lv2 x42-plugins calf-plugins`),
así que entran directo en la ISO sin compilar nada extra.

## Por qué esto no es "un premio consuelo"

LSP en particular tiene fama en la comunidad de audio libre de estar a la altura de plugins
comerciales caros — no es una alternativa "más o menos parecida", es una herramienta profesional
que varios ingenieros de mezcla usan en producción real. La diferencia con FabFilter no es tanto
de calidad de algoritmo sino de pulido de interfaz (que acá vamos a construir nosotros, con
nuestra propia identidad visual) y de curva de marketing.

## Dónde entra en el Editor de Nodos

Las categorías **DINÁMICA** y **ECUALIZADOR** del sidebar de categorías (`docs/mockups.md`) hoy
listan nombres genéricos ("Compressor", "Optical Comp", "Parametric-3"). El paso siguiente, si se
quiere, es reemplazarlos por los nombres reales de estos plugins (`LSP Compressor`, `x42 darc`,
`Calf Equalizer 8 Band`) para que el mockup refleje exactamente lo que va a cargar Guitarix.
