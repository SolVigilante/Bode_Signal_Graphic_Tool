# Bode_Signal_Graphic_Tool
Este código de python permite superponer dos curvas de Bode o de señales proveniente de un .csv. Admite archivos provenientes de un osciloscopio o de un software de simulación(Probado particularmente con LTSPice).

# Librerias Necesarias
1)*numpy*
instalación en windows: pip install numpy

2)*matplotlib*
pip install matplotlib

# Ejecución

Para ejecutar el código es necesario introducirle el modo (signal o bode según corresponda) y los dos archivos .csv. Los archivos deben estar alojados en la carpeta del código. 

*Ejemplo de comando*

python3 graficador.py signal senal.csv senal2.csv 

python3 graficador.py bode  Pasa_Bajos.csv Bode_filtro.csv

# Limitaciones
Permite graficar únicamente dos señales en simultáneo. 

