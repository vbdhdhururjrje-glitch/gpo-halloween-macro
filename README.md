# GPO Halloween Macro

## Русский

Макрос для Windows, который записывает и воспроизводит последовательности нажатий клавиатуры и действий мыши. Маркеры `DOOR` связывают записанный маршрут с проверкой игровых уведомлений через OCR.

> Используйте программу только там, где автоматизация разрешена правилами игры и платформы. Макрос может выполнять неожиданные действия. Не запускайте его от имени администратора без необходимости.

### Скачать

- [Последний релиз](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest)
- [Скачать ZIP приложения](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip)
- [Исходный код](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro)
- [Tesseract OCR для Windows — сборки UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
- [Официальное руководство по установке Tesseract](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)

### Установка и скачивание через PowerShell

Откройте PowerShell и выполните команды. ZIP скачается в Downloads, распакуется, а установщик поместит программу в `%LOCALAPPDATA%\Programs\GPO Halloween Macro` и запустит её. Права администратора не нужны.

```powershell
$zip = Join-Path $HOME 'Downloads\GPO-Halloween-Macro-Windows.zip'
$folder = Join-Path $HOME 'Downloads\GPO-Halloween-Macro'
New-Item -ItemType Directory -Path (Split-Path $zip) -Force | Out-Null
Invoke-WebRequest 'https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip' -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath $folder -Force
& (Join-Path $folder 'GPO Halloween Macro\Install-GPOHalloweenMacro.ps1') -ArchivePath $zip
```

Если Windows блокирует PowerShell-скрипт, сначала прочитайте `Install-GPOHalloweenMacro.ps1` и соблюдайте правила выполнения скриптов на вашем компьютере. Не меняйте системную политику выполнения ради этого приложения.

Установщик скачивает последнюю сборку, устанавливает её и запускает. В публичном ZIP находятся авторские настройки и маршрут. Установщик импортирует их только в новый профиль, если нет ни `settings.json`, ни стандартного `route.json`; существующие данные не перезаписываются. Настройки OCR-области сделаны под экран автора и могут требовать изменения на другом компьютере.

Можно также распаковать ZIP и запустить `GPO Halloween Macro.exe` непосредственно из папки. Не переносите один EXE отдельно: рядом с ним необходима папка `_internal`. Python для готовой сборки не требуется. Для OCR отдельно установите Tesseract.

### Установка Tesseract OCR

1. Скачайте установщик для Windows со страницы [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki).
2. В установщике выберите английские языковые данные (**English**): игровые уведомления, которые распознаёт макрос, отображаются по-английски.
3. В приложении откройте вкладку **OCR**. Укажите `tesseract.exe` кнопкой обзора или добавьте каталог Tesseract в `PATH`.
4. Частый путь установки: `C:\Program Files\Tesseract-OCR\tesseract.exe`.
5. Нажмите **Capture and recognize** и проверьте, что текст виден в поле результата.

Python-библиотека `pytesseract` — это только связующее звено; она не устанавливает сам движок Tesseract.

### Подробная работа с макросом

#### Подготовка

1. Запустите игру. Установите нужное разрешение, масштаб интерфейса и положение игрового окна. Во время записи и воспроизведения не меняйте их: координаты мыши и OCR-области зависят от расположения интерфейса.
2. Настройте Tesseract на вкладке **OCR**.
3. Настройте рамку захвата OCR так, чтобы в неё полностью попадали игровые уведомления. Кнопка редактирования позволяет двигать и менять размер рамки; сброс возвращает стандартную область.
4. Проверьте на вкладке **Settings** слот сумки, задержку старта, скорость, интервалы и горячие клавиши.
5. Перед воспроизведением активируйте окно игры и убедитесь, что персонаж и камера находятся в начальной позиции маршрута.

#### Запись маршрута

1. Нажмите **Record route** или F10. Макрос выберет настроенный слот сумки и начнёт записывать клавиатуру и мышь.
2. Пройдите желаемый маршрут. Делайте это в том темпе и последовательности, которые должны повторяться.
3. У каждой двери выберите маркер `DOOR` и нажмите **Mark point** или F9 в точке взаимодействия. Запишите нажатие E для двери в нужном месте маршрута: DOOR-маркер должен корректно соответствовать этому действию.
4. Нажмите **Finish recording** или клавишу Stop (по умолчанию F8), чтобы завершить запись.
5. На вкладке **Route** нажмите **Save route** и сохраните JSON-маршрут.

Чтобы использовать существующий маршрут, нажмите **Load route**. Запись нового маршрута заменяет текущий маршрут в памяти, поэтому сначала сохраните нужный маршрут.

#### Воспроизведение и двери

1. Загрузите маршрут и проверьте число действий и маркеров.
2. Активируйте игру, встаньте в начальной точке и нажмите F6.
3. Макрос выполняет записанные действия. У двери он ждёт привязанное нажатие E и проверяет текст в выбранной OCR-области.
4. Если OCR ещё не подтвердил результат двери, макрос делает повторные нажатия E с заданным интервалом. Стандартно интервал равен 5 секундам, лимит — 5 нажатий E на дверь. После достижения лимита макрос продолжает сканировать OCR, но больше не нажимает E.
5. Маршрут продолжается после устойчивого распознавания поддерживаемого результата: получения/кражи конфет, сообщения о повторном посещении/перезарядке или заполненной корзины. Вход в дом, появление персонажа или произвольный текст сами по себе не являются подтверждением.
6. Следите за воспроизведением. Если персонаж отошёл от записанного маршрута, поставьте макрос на паузу F7 или остановите F8/F12. Программа не определяет автоматически, что игрок вручную подошёл к двери вне маршрута.

#### Горячие клавиши по умолчанию

| Клавиша | Действие |
| --- | --- |
| F6 | Старт / продолжение |
| F7 | Пауза |
| F8 | Остановка |
| F9 | Маркер `DOOR` во время записи |
| F10 | Начать запись |
| F12 | Аварийная остановка |

Горячие клавиши и параметры можно изменить в **Settings**.

#### Настройки, маршрут и приватность

Параметры приложения и стандартный маршрут хранятся локально в `%USERPROFILE%\GPO_Halloween_Macro` (`settings.json` и `route.json`). Кнопка возврата настроек к стандартным значениям не удаляет маршрут.

Маршрут содержит записанные клавиши, движения и клики мыши, временные метки и положения маркеров. Он может раскрывать игровой путь или способ взаимодействия — проверьте файл перед тем, как делиться им.

Публичный релиз содержит авторский маршрут и настройки. Из переносимых настроек удалены абсолютные пути к компьютеру автора и сохранённые состояния перезарядок. Получателю следует проверить настройки OCR-рамки под свой экран.

### Запуск из исходного кода и тесты

Нужны Windows 10/11 и Python 3.10 или новее:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python gpo_halloween_macro_prototype.py
```

Сборка Windows-папки с приложением и ZIP:

```powershell
python -m pip install -r requirements-build.txt
.\build_windows.ps1
```

Чтобы явно включить настройки и маршрут текущего пользователя в архив, запустите `.\build_windows.ps1 -IncludePersonalProfile`. Полученный ZIP содержит записанные игровые действия — распространяйте его только если это намеренно.

Запуск тестов:

```powershell
python -m unittest discover -s tests
```

## English

Windows application for recording and replaying keyboard and mouse actions. `DOOR` markers connect a saved route with OCR checks for in-game notifications.

> Use the application only where automation is allowed by the game and platform rules. The macro may perform unintended actions. Do not run it as Administrator without a specific need.

### Download

- [Latest release](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest)
- [Download the Windows ZIP](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip)
- [Source code](https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro)
- [Tesseract OCR for Windows — UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki)
- [Official Tesseract installation guide](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)

### Download and install with PowerShell

Open PowerShell and run these commands. They download the ZIP to Downloads, extract it, and run the installer, which installs the application under `%LOCALAPPDATA%\Programs\GPO Halloween Macro` and launches it. Administrator privileges are not required.

```powershell
$zip = Join-Path $HOME 'Downloads\GPO-Halloween-Macro-Windows.zip'
$folder = Join-Path $HOME 'Downloads\GPO-Halloween-Macro'
New-Item -ItemType Directory -Path (Split-Path $zip) -Force | Out-Null
Invoke-WebRequest 'https://github.com/vbdhdhururjrje-glitch/gpo-halloween-macro/releases/latest/download/GPO-Halloween-Macro-Windows.zip' -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath $folder -Force
& (Join-Path $folder 'GPO Halloween Macro\Install-GPOHalloweenMacro.ps1') -ArchivePath $zip
```

If Windows blocks the PowerShell script, inspect `Install-GPOHalloweenMacro.ps1` first and follow your computer's script execution policy. Do not change the machine-wide policy for this application.

The installer downloads the latest build, installs it, and launches it. The public ZIP contains the author's settings and route. They are imported only into a fresh profile with neither `settings.json` nor the default `route.json`; existing user data is not overwritten. The OCR region was configured for the author's display and may need adjustment on another computer.

You may also extract the ZIP and run `GPO Halloween Macro.exe` directly from its folder. Do not move the EXE by itself; the adjacent `_internal` directory is required. Python is not required for the packaged build. Tesseract must be installed separately for OCR.

### Install Tesseract OCR

1. Download the Windows installer from [UB Mannheim Tesseract builds](https://github.com/UB-Mannheim/tesseract/wiki).
2. Select the **English** language data in the installer; the in-game notifications recognized by the macro are in English.
3. Open the application's **OCR** tab. Browse to `tesseract.exe`, or add the Tesseract directory to `PATH`.
4. A common installation path is `C:\Program Files\Tesseract-OCR\tesseract.exe`.
5. Click **Capture and recognize** and confirm that recognized text appears in the results field.

The Python package `pytesseract` is only a connector; it does not install the Tesseract engine.

### Detailed usage

#### Before recording or playback

1. Start the game and set the desired resolution, UI scale, and window position. Keep them unchanged while recording and replaying; mouse coordinates and the OCR region depend on the UI layout.
2. Configure Tesseract on the **OCR** tab.
3. Adjust the OCR capture box so that in-game notifications fit completely inside it. Use the region controls to move/resize the box or reset it to the default.
4. Review the bag slot, startup delay, playback speed, intervals, and hotkeys under **Settings**.
5. Before playback, focus the game and place the character and camera at the route's recorded starting position.

#### Record a route

1. Click **Record route** or press F10. The macro selects the configured bag slot and starts recording keyboard and mouse input.
2. Follow the route you want to replay, in the order and at the pace you want recorded.
3. At each door, select the `DOOR` marker and click **Mark point** or press F9 at the interaction point. Record the E press at the corresponding place in the route so the marker is associated with the interaction.
4. Click **Finish recording** or press Stop (F8 by default).
5. On the **Route** tab, click **Save route** and save the JSON file.

Use **Load route** to open an existing route. Starting a new recording replaces the route currently in memory, so save any route you need first.

#### Playback and door handling

1. Load a route and review its action and marker counts.
2. Focus the game, return to the recorded starting position, and press F6.
3. The macro replays the recorded actions. At a door it waits for the linked E press, then checks the selected OCR region for text.
4. If OCR has not confirmed the door result, the macro retries E at the configured interval. The default interval is 5 seconds, with a maximum of 5 E presses per door. After that limit, OCR scanning continues but no more E presses are sent.
5. The route continues after a stable recognition of a supported result: candies received/stolen, a revisit/cooldown notification, or a full basket. Entering a house, seeing an NPC, or unrelated text alone is not treated as confirmation.
6. Monitor playback. If the character leaves the recorded route, pause with F7 or stop with F8/F12. The macro does not automatically detect that the player has manually approached a door outside the route.

#### Default hotkeys

| Key | Action |
| --- | --- |
| F6 | Start / resume |
| F7 | Pause |
| F8 | Stop |
| F9 | Add a `DOOR` marker while recording |
| F10 | Start recording |
| F12 | Emergency stop |

Hotkeys and application options can be changed in **Settings**.

#### Settings, routes, and privacy

Application settings and the default route are stored locally under `%USERPROFILE%\GPO_Halloween_Macro` (`settings.json` and `route.json`). Resetting settings to their defaults does not delete the route.

A route contains recorded keys, mouse movement/clicks, timestamps, and marker positions. It may reveal a game-specific path or interaction pattern; review it before sharing.

The public release includes the author's route and settings. Machine-specific absolute paths and saved cooldown state are removed from the portable settings. Recipients should adjust the OCR region for their own display.

### Run from source and tests

Requires Windows 10/11 and Python 3.10 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python gpo_halloween_macro_prototype.py
```

Build the Windows application folder and ZIP:

```powershell
python -m pip install -r requirements-build.txt
.\build_windows.ps1
```

To explicitly include the current Windows user's settings and route in the archive, run `.\build_windows.ps1 -IncludePersonalProfile`. The resulting ZIP contains recorded game actions; share it only if intended.

Run the tests:

```powershell
python -m unittest discover -s tests
```

## License

Released under the MIT License. See [LICENSE](LICENSE).
