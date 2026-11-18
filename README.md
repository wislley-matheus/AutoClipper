# 🎬 Twitch Auto Clipper

Sistema modular e desacoplado em Python para detecção automática de momentos virais (picos de hype) em transmissões da Twitch, recorte de vídeo em formato vertical (9:16 - 1080x1920) e publicação automatizada em redes sociais (YouTube Shorts, TikTok, Instagram Reels).

---

## 🏗️ Arquitetura e Módulos

O projeto é estruturado em **4 módulos independentes**, interligados por contratos de dados padronizados (`core/models.py`) e um barramento assíncrono de eventos (`core/event_bus.py`). Cada módulo pode ser executado, testado e evoluído isoladamente:

```
                          ┌────────────────────────┐
                          │     chat_listener      │
                          │ (Twitch IRC / Mock)    │
                          └───────────┬────────────┘
                                      │ ChatMessage Stream
                                      ▼
                          ┌────────────────────────┐
                          │     hype_detector      │
                          │ (Sliding Window & MPS) │
                          └───────────┬────────────┘
                                      │ HypeEvent
                                      ▼
                          ┌────────────────────────┐
                          │    video_processor     │
                          │ (FFmpeg 9:16 Vertical) │
                          └───────────┬────────────┘
                                      │ ClipMetadata (MP4)
                                      ▼
                          ┌────────────────────────┐
                          │    social_uploader     │
                          │ (YouTube, TikTok, IG)  │
                          └────────────────────────┘
```

1. **`chat_listener`**: Conecta ao chat da Twitch via IRC (com suporte a conexões anônimas `justinfan` ou token OAuth) ou gera mensagens simuladas com rajadas de hype.
2. **`hype_detector`**: Processa o fluxo em tempo real via algoritmo de janela deslizante (sliding window), calculando a taxa de mensagens por segundo (MPS), densidade de palavras-chave virais (*POG, LUL, KEKW, CLIP IT*), emotes e doações de bits com pesos configuráveis e controle de cooldown.
3. **`video_processor`**: Consome o evento de hype, corta o trecho correspondente com buffer pré e pós-hype e formata para proporção 9:16 vertical (1080x1920) com renderização via FFmpeg.
4. **`social_uploader`**: Recebe o clipe finalizado e distribui concorrentemente para YouTube Shorts, TikTok e Instagram Reels, fornecendo logs de status e links de publicação.

---

## 📁 Estrutura de Pastas

```
twitch-auto-clipper/
├── .env.example                  # Template com todas as variáveis de ambiente
├── .env                          # Configurações ativas do projeto
├── .gitignore                    # Regras de exclusão do Git
├── pyproject.toml                # Metadados e configuração do pacote
├── requirements.txt              # Dependências do projeto
├── README.md                     # Documentação de uso
├── main.py                       # Orquestrador central e CLI unificado
├── core/                         # Núcleo compartilhado
│   ├── __init__.py
│   ├── config.py                 # Parser do .env (zero dependências obrigatórias)
│   ├── models.py                 # DTOs: ChatMessage, HypeEvent, ClipMetadata, UploadResult
│   └── event_bus.py              # Barramento pub/sub assíncrono
├── modules/                      # 4 Módulos desacoplados
│   ├── chat_listener/            # Módulo 1: Ouvinte de chat
│   │   ├── base.py               # Interface BaseChatListener
│   │   ├── twitchio_listener.py  # Conector TwitchIO oficial (EventSub/Chat)
│   │   ├── mock_listener.py      # Simulador de chat com rajadas de hype
│   │   ├── twitch_listener.py    # Conexão nativa IRC da Twitch
│   │   └── cli.py                # Runner CLI para teste isolado
│   ├── hype_detector/            # Módulo 2: Detector de hype
│   │   ├── base.py               # Interface BaseHypeDetector
│   │   ├── moving_average_detector.py # Média móvel (5s, 3x spike, salva 40 msgs em JSON)
│   │   ├── detector.py           # Janela deslizante e cálculo de score
│   │   ├── rules.py              # Pesos e regras de detecção
│   │   └── cli.py                # Runner CLI para teste isolado
│   ├── video_processor/          # Módulo 3: Processador de vídeo
│   │   ├── base.py               # Interface BaseVideoProcessor
│   │   ├── mock_processor.py     # Gerador sintético via FFmpeg
│   │   ├── ffmpeg_processor.py   # Pipeline FFmpeg real com blur vertical
│   │   └── cli.py                # Runner CLI para teste isolado
│   └── social_uploader/          # Módulo 4: Uploader de redes sociais
│       ├── base.py               # Interface BaseSocialUploader
│       ├── mock_uploader.py      # Uploader simulado multi-plataforma
│       ├── youtube_uploader.py   # Conector YouTube Data API v3
│       └── cli.py                # Runner CLI para teste isolado
├── storage/                      # Pasta de armazenamento
│   ├── clips/                    # Arquivos .mp4 gerados
│   └── events/                   # Arquivos JSON das 40 mensagens do 'Clipe Detectado'
└── tests/                        # Bateria de testes automatizados (11 testes)
    ├── test_chat_listener.py
    ├── test_twitchio_listener.py
    ├── test_hype_detector.py
    ├── test_moving_average_detector.py
    ├── test_video_processor.py
    └── test_social_uploader.py
```

---

## ⚙️ Configuração via `.env`

Copie o arquivo `.env.example` para `.env` (já criado por padrão):

```bash
cp .env.example .env
```

Principais parâmetros:

| Variável | Padrão | Descrição |
| :--- | :--- | :--- |
| `MOCK_MODE` | `true` | Ativa simuladores em todos os módulos (ideal para dev e testes locais) |
| `TWITCH_CHANNEL` | `gaules` | Canal a ser monitorado |
| `HYPE_WINDOW_SECONDS`| `10` | Janela de tempo deslizante (segundos) |
| `HYPE_THRESHOLD_MPS` | `4.0` | Limiar de mensagens por segundo para disparar o Hype |
| `HYPE_MIN_SCORE` | `10.0` | Pontuação mínima combinada (MPS + Keywords + Bits) |
| `HYPE_COOLDOWN_SECONDS` | `45` | Tempo de espera mínimo entre clipes |
| `CLIP_DURATION_SECONDS` | `30` | Duração do clipe final |
| `VIDEO_VERTICAL_ASPECT`| `true` | Força proporção 9:16 vertical (1080x1920) |
| `YOUTUBE_ENABLED` | `true` | Ativa publicação no YouTube Shorts |
| `TIKTOK_ENABLED` | `true` | Ativa publicação no TikTok |
| `INSTAGRAM_ENABLED` | `false`| Ativa publicação no Instagram Reels |

---

## 🧪 Testando Cada Módulo Isoladamente

Cada módulo possui seu próprio utilitário CLI em `cli.py`, permitindo testar seu comportamento sem depender dos outros:

### 1. Testar `chat_listener`:
```bash
python3 modules/chat_listener/cli.py --mode mock --count 10 --spike
```

### 2. Testar `hype_detector`:
```bash
python3 modules/hype_detector/cli.py --mps 3.0 --score 8.0
```

### 3. Testar `video_processor`:
```bash
python3 modules/video_processor/cli.py --duration 5.0 --vertical
```

### 4. Testar `social_uploader`:
```bash
python3 modules/social_uploader/cli.py --platforms youtube tiktok
```

---

## 🚀 Executando o Pipeline Completo

### Demonstração End-to-End (Mock Mode)
Executa todo o fluxo (Chat -> Detecção de Hype -> Geração de Vídeo FFmpeg 9:16 -> Upload Multi-plataforma) e encerra após 1 clipe:
```bash
python3 main.py --demo
```

### Modo Ao Vivo (Twitch IRC Real)
Monitora o canal real configurado no `.env`:
```bash
python3 main.py --live --channel gaules
```

---

## 🔬 Executando a Bateria de Testes

Os testes usam o runner nativo do Python (sem necessidade de instalar pacotes externos):

```bash
python3 -m unittest discover -s tests -t .
```
