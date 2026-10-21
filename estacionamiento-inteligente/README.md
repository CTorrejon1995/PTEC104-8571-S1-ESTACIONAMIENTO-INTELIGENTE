# Estacionamiento inteligente — Fase 1

Prototipo local de evaluación IoT. Esta fase utiliza datos **simulados**, no sensores reales.

## Componentes
- `mosquitto`: broker MQTT.
- `simulator`: simula ocho sensores ultrasónicos y eventos de entrada por sensor infrarrojo.
- `processor`: procesa distancias, calcula ocupación y publica estados/resumen.

## Requisitos
Docker Desktop funcionando con el backend WSL 2.

## Ejecutar
Desde la raíz del repositorio:

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f simulator processor
```

Para observar el resumen MQTT en otra terminal:

```powershell
docker compose exec mosquitto mosquitto_sub -h localhost -t "parking/summary" -v
```

Para observar los estados individuales:

```powershell
docker compose exec mosquitto mosquitto_sub -h localhost -t "parking/state/#" -v
```

Detener los servicios:

```powershell
docker compose down
```

Detener y borrar también los volúmenes persistentes:

```powershell
docker compose down -v
```

## Tópicos MQTT
| Tópico | Productor | Contenido |
|---|---|---|
| `parking/sensors/<puesto>/distance` | simulator | Distancia simulada en cm |
| `parking/gate/entry` | simulator | Evento de ingreso simulado |
| `parking/state/<puesto>` | processor | Estado calculado de cada puesto |
| `parking/summary` | processor | Resumen de ocupación e ingresos |

El umbral inicial es 30 cm: una distancia menor o igual se interpreta como ocupado. Es un valor de demostración que deberá calibrarse con el sensor y la instalación reales.

## Importante para el despliegue
Esta configuración MQTT permite conexiones anónimas y solo debe usarse en el entorno local de desarrollo. Antes de exponer el broker en una red real hay que configurar autenticación, ACL y TLS. En la arquitectura final, el dispositivo hará conexiones salientes HTTPS a la API en la nube.

## Próximas fases
1. Buffer local y sincronización resiliente.
2. API REST y persistencia.
3. Dashboard, autenticación y roles.
4. Configuración remota.
5. Adaptador de hardware real y evaluación de consumo.
