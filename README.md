# Bode_Signal_Graphic_Tool

Script en Python para superponer **dos o más archivos CSV** en un mismo
gráfico, pensado para trabajo de laboratorio de electrónica:

- **Diagramas de Bode** (magnitud en dB y fase en grados vs. frecuencia)
- **Señales de osciloscopio / transitorios** (amplitud vs. tiempo)

Funciona con archivos exportados por **osciloscopios** (Tektronix, Rigol,
Keysight, etc.) y por **LTSpice** (`File > Export Data as Text`), y **no
hace falta que los archivos tengan el mismo formato entre sí** — el
script detecta cada uno por separado.

Si un mismo CSV trae más de una señal (por ejemplo CH1/CH2/CH3/CH4 de un
osciloscopio, o varios nodos V(a)/V(b) exportados juntos desde LTSpice),
el script las detecta automáticamente y las grafica todas, sin que
tengas que separar el archivo a mano.

---

## 1. Requisitos

- Python 3.8 o superior
- Librerías `matplotlib` y `numpy`

Instalación de las librerías (una sola vez):

```bash
pip install matplotlib numpy
```

Si estás en Windows y `pip` no anda, probá `python -m pip install matplotlib numpy`.

## 2. Instalación

No hay instalación real: es un único archivo (`overlay_csv.py`). Guardalo
en una carpeta y desde ahí corré los comandos, o pasale la ruta completa
al script y a los CSV.

## 3. Uso básico

```
python overlay_csv.py <modo> <archivo1.csv> <archivo2.csv> [...más archivos] [opciones]
```

`<modo>` es **obligatorio** y puede ser:

| Modo | Qué grafica | Eje X | Eje(s) Y |
|---|---|---|---|
| `bode` | Diagrama de Bode | Frecuencia (escala log) | Magnitud [dB] arriba, Fase [°] abajo |
| `signal` | Señal temporal | Tiempo | Amplitud [V] |

Podés pasar **2, 3, 10, los archivos que necesites** — no hay límite.

### Ejemplos

Comparar una medición de osciloscopio contra una simulación de LTSpice:
```bash
python overlay_csv.py bode medido.csv simulado.csv --labels "Medición" "LTSpice" --title "Bode - Filtro RLC"
```

Comparar tres simulaciones con distintos valores de R:
```bash
python overlay_csv.py bode sim_R1k.csv sim_R2k.csv sim_R3k.csv \
    --labels "R=1k" "R=2k" "R=3k" --title "Barrido de R"
```

Superponer canales de osciloscopio (entrada y salida):
```bash
python overlay_csv.py signal ch1.csv ch2.csv --labels "Entrada" "Salida"
```

Guardar el gráfico como imagen en vez de mostrarlo en pantalla:
```bash
python overlay_csv.py bode medido.csv simulado.csv --save resultado.png
```
Si no usás `--save`, se abre una ventana con el gráfico (necesitás estar
corriendo el script en tu máquina, con entorno gráfico — no funciona así
en un servidor remoto sin pantalla).

## 4. Múltiples señales dentro de un mismo archivo

No hace falta que cada CSV tenga una sola señal. El script detecta
automáticamente:

- **Osciloscopios multicanal**: columnas tipo `TIME, CH1, CH2, CH3, CH4`
  → cada canal se grafica como una traza separada.
- **LTSpice con varios nodos exportados juntos**: columnas tipo
  `Freq., V(a), V(b), V(c)` → cada nodo se detecta como una traza Bode
  independiente (reconoce el valor complejo `(magnitud,fase)` en la
  celda, sin importar el nombre de columna).
- **Pares Gain/Phase repetidos**: columnas tipo `CH1 Gain, CH1 Phase,
  CH2 Gain, CH2 Phase` se emparejan automáticamente en el orden en que
  aparecen.

Cuando un archivo aporta **una sola señal**, el label que le pusiste en
`--labels` se usa tal cual. Cuando aporta **varias**, se les agrega el
nombre de columna automáticamente:

```bash
python overlay_csv.py signal osciloscopio_4ch.csv --labels "Osciloscopio"
# -> leyenda: "Osciloscopio – CH1", "Osciloscopio – CH2", "Osciloscopio – CH3", "Osciloscopio – CH4"
```

> **Nota:** para superponer, necesitás al menos **dos señales en
> total** entre todos los archivos — pueden venir de un solo archivo
> multicanal, no hace falta que sean dos archivos distintos.

Si un archivo tiene columnas de "ruido" que no querés graficar (por
ejemplo una columna de índice o una medición que no te interesa), usá
los overrides de columna (sección 6) para forzar una sola señal en vez
de la detección automática.

## 5. `--labels`: un nombre por archivo, no por señal

`--labels` espera **un nombre por cada archivo** que pasaste, en el
mismo orden — no uno por señal individual. Si un archivo trae varias
señales, todas comparten ese label como prefijo (ver sección 4).

Si no pasás `--labels`, el script usa el nombre del archivo (sin
extensión) como label por defecto.

```bash
# 2 archivos -> 2 labels
python overlay_csv.py bode a.csv b.csv --labels "Medido" "Simulado"
```

Si la cantidad de labels no coincide con la cantidad de archivos, el
script tira un error explicándolo — no se puede pasar 3 labels para 2
archivos, por ejemplo.

## 6. Cuándo (y cómo) forzar las columnas a mano

El script intenta detectar automáticamente qué columna es cuál según su
nombre (`Freq.`, `Time`, `V(...)`, `Gain`, `Phase`, `CH1`, etc.) y, en
`bode`, además revisa el contenido real de cada celda para encontrar
columnas de valor complejo. Si tu archivo tiene nombres de columna poco
usuales y el gráfico sale vacío, con datos raros, o mezclando cosas que
no correspondían, forzalo a mano con estas opciones (van **después**
del modo y los archivos):

| Opción | Para qué sirve |
|---|---|
| `--time-col` | Columna de tiempo (nombre o índice, ej. `Time` o `0`) — modo `signal` |
| `--volt-col` | Columna de amplitud/tensión — modo `signal` |
| `--freq-col` | Columna de frecuencia — modo `bode` |
| `--mag-col` | Columna de magnitud/ganancia — modo `bode` |
| `--phase-col` | Columna de fase — modo `bode` |
| `--mag-linear` | La magnitud viene en escala lineal, no en dB (el script la convierte) |
| `--delimiter` | Forzar el separador del CSV (`,`, `;`, o `\t` para tab) |
| `--skiprows` | Forzar en qué fila (contando desde 0) está el encabezado real, si el autodetect de metadata se equivoca |

**Importante:** si usás `--mag-col` o `--phase-col`, el script deja de
buscar varias señales en ese archivo y toma **una sola** traza con esas
columnas puntuales. Es la forma de "apagar" la detección múltiple para
un archivo en particular.

Ejemplo forzando columnas:
```bash
python overlay_csv.py bode datos_raros.csv sim.csv \
    --freq-col "Frequency (Hz)" --mag-col "Gain (dB)" --phase-col "Phase (deg)"
```

También podés usar el **índice de columna** (empezando en 0) en vez del
nombre, si el nombre tiene caracteres raros:
```bash
python overlay_csv.py bode datos.csv sim.csv --freq-col 1 --mag-col 3 --phase-col 4
```

## 7. Personalización visual

| Opción | Qué hace |
|---|---|
| `--title "texto"` | Título del gráfico |
| `--style white` o `--style dark` | Fondo claro (default) u oscuro |
| `--save archivo.png` | Guarda la imagen en vez de abrir una ventana |

Con más de 10 señales superpuestas, el script cambia automáticamente del
ciclo de colores estándar a un colormap continuo, para que las curvas
sigan siendo distinguibles.

## 8. Formatos de CSV soportados / cosas que el script resuelve solo

No necesitás limpiar el CSV antes de usarlo. El script ya maneja:

- **Encoding Latin-1/ISO-8859**, típico de exports de LTSpice y algunos
  osciloscopios donde el símbolo `°` se ve mal en editores que esperan
  UTF-8.
- **Filas de metadata** antes del encabezado real (modelo del
  instrumento, firmware, fecha, etc.) — las detecta y las salta.
- **Delimitador** (coma, punto y coma, o tab) — lo detecta solo.
- **Formato complejo de LTSpice** para AC analysis, tipo
  `(-3.96e-04dB,-5.47e-01°)`, incluida la unidad pegada al número sin
  espacio.
- **Columnas de índice** (`#`, `Index`, `N°`, `Sample`, etc.) — se
  ignoran, no se confunden con una señal real.

## 9. Errores comunes y qué significan

| Mensaje | Qué pasó | Qué hacer |
|---|---|---|
| `Hay que pasar al menos dos archivos CSV para superponer.` | Solo pasaste un archivo | Agregá al menos un segundo archivo |
| `Pasaste N archivos pero M labels; tienen que coincidir.` | La cantidad de `--labels` no matchea la de archivos | Poné un label por archivo, ni más ni menos |
| `Después de leer los archivos quedaron menos de dos señales para superponer.` | El autodetect no encontró suficientes columnas válidas | Revisá el CSV a ojo y forzá las columnas con las opciones de la sección 6 |
| `No se encontró la columna 'X'` | Usaste `--mag-col`/`--freq-col`/etc. con un nombre que no existe en el header | Fijate el nombre exacto de la columna (podés abrir el CSV en un editor de texto) o usá el índice numérico en su lugar |
| `Aviso: no se encontraron señales en archivo.csv, se omite.` | Ese archivo en particular no tenía datos usables | Revisá que el archivo no esté vacío o corrupto |

## 10. Resumen rápido de todas las opciones

```
python overlay_csv.py {bode,signal} archivo1.csv archivo2.csv [...] [opciones]

  --labels L1 L2 [...]      Un nombre por archivo (no por señal)
  --title "texto"           Título del gráfico
  --style {white,dark}      Fondo claro u oscuro (default: white)
  --save archivo.png        Guardar como imagen en vez de mostrar en pantalla
  --delimiter ','           Forzar separador del CSV
  --skiprows N              Forzar fila de encabezado (0-based)
  --time-col COL            [signal] columna de tiempo
  --volt-col COL            [signal] columna de tensión (fuerza 1 sola señal)
  --freq-col COL            [bode] columna de frecuencia
  --mag-col COL             [bode] columna de magnitud (fuerza 1 sola señal)
  --phase-col COL           [bode] columna de fase (fuerza 1 sola señal)
  --mag-linear              [bode] la magnitud viene en escala lineal, no en dB
```

`COL` puede ser el nombre de la columna (tal como aparece en el CSV) o
su número de índice empezando en 0.

# Limitaciones
No punciona con el comando de .step param de LTSpice.