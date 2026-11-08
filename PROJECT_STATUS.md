# Текущий этап: аудит защиты и удобства панели

## Объём
Проверить проект и работающую панель без Computer Use, выявить раскрытие конфигов и риски DNS/IPv6, сравнить с существующими проектами, подготовить проверенные улучшения. Оперативные сведения о сервере остаются в игнорируемом .ops-tmp/PROJECT_STATUS_migration_private.md.

## Подтверждено
- Серверный перенос клиентов завершён ранее. Обнаружен оставшийся лимит интерфейса 64 при увеличенном серверном лимите.
- Конфиги на сервере доступны только root; в проверенных audit JSONL маркеров ключей/конфигов не найдено. Это выборочная проверка, не доказательство отсутствия любых утечек.
- AWG-конфиги содержат IPv4-маршрут без IPv6. Реальная утечка на устройстве не доказана. На сервере нет выхода в IPv6.
- Приватные данные в открытой вкладке не имели срока показа и очистки при истечении входа/скрытии страницы.
- История вкладки ошибочно описывалась как семидневный журнал. Перенос dual-stack подсети backend пока не поддерживает.

## В работе
Первый блок защиты и удобства установлен ранее. Составной выпуск API серверного журнала установлен после отдельного согласования. Обе веб-службы active, runtime marker и post-install проверки подтверждены.

## Ограничения
Клиентская защита при обрыве VPN и DNS/IPv6 требуют проверки на устройствах. Серверная панель не может подтвердить это по одному конфигу. Изменение firewall, клиентских маршрутов, разрешений служб и deployment требуют отдельного конкретного согласования.

## Результат повторного ревью и тестов
- Лимит интерфейса согласован с backend: 256 записей; сценарий 124 клиентов проверен.
- Имя .conf совпадает с именем клиента при создании и повторном скачивании; Unicode/пробелы сохраняются, недопустимые и зарезервированные Windows-имена безопасно преобразуются.
- Секреты скрываются через 2 минуты, при скрытии/уходе со страницы, выходе и ответе 401. Поздние ответы не возвращают конфиг и не подменяют список другого профиля. Старый таймер закрытого окна не стирает новую форму. Буфер обмена и скачанные файлы автоматически не отзываются.
- Deadline чтения 45 секунд; мутаций 340 секунд с учётом лимитов helper/relay. Неопределённый результат не объявляется успешным или заведомо не выполненным; автоматического повтора создания нет.
- Реальный журнал обозначен как история текущей вкладки. Формы других профилей сохраняют незавершённые правки. Неподдерживаемый перенос dual-stack подсети выключен с объяснением.
- Подсказки о повторном импорте, IPv6 и проверке DNS/защиты при обрыве помещены в компактный раскрываемый блок; мобильный размер визуально проверен на синтетических данных.
- Auth: отказ при >72 UTF-8 байтах для bcrypt, безопасный отказ при исключении verifier и недопустимом имени. Увеличенные серверные конфиги поддерживаются также изменением портов и журналами восстановления.
- Windows Python: 213 тестов OK, 53 штатных POSIX/root skips. GitHub Actions Linux CI для этого commit прошёл на Python 3.11, 3.12 и 3.13: по 213 тестов OK и по 12 штатных skips. Все восемь browser-сценариев прошли; privacy, create, profiles и server audit проверены. Public safety, Git history safety, diff check и JavaScript syntax PASS.
- Первая версия установлена: проверены 6/12/124 клиента, VPN-конфигурации и множества peers не изменились. При проверке перезапуска учитываются готовность сокетов и нефиксированный порядок peers; предыдущая версия сохранена для отката.

## Клиентская диагностика
- Выбранный исходный WireSock-профиль обновлён после явного согласия: доменный endpoint, IPv4+IPv6 default routes. Ключи и исключения сохранены.
- Пробное включение Kill Switch не привело к соединению. По поздней проверке он выключен, туннель не подключён. У пользователя есть второй профиль того же клиента с прежним IPv4-only маршрутом; глобальные параметры и выбор профиля менялись пользователем во время диагностики.
- Подтверждён настоящий криптографический AWG2-handshake через VPNUS. Прямой Ethernet-маршрут проверен; две попытки не получили ответа, уточняющий захват на сервере не увидел пакетов. Это проблема прямого UDP-пути, а не доказанная блокировка всего IP или атрибуция регулятору.
- В WireSock журнале есть cleanup error 87 и применение глобальной SIP-маскировки; причинность маскировки не доказана. Серверная проверка ключей успешна.
- Профильные файлы Windows читаются группой Users. Ограничение ACL/шифрование профилей требует отдельного проверенного изменения; пока не выполнено.
- DNS/IPv6-утечки на работающем WireSock и fail-closed поведение при реальном обрыве остаются непроверенными. Нет глобального IPv6-маршрута на текущем ПК; отсутствие IPv6 сегодня не гарантирует защиту в другой сети.

## Следующие продуктовые улучшения
1. Проверка доступности endpoint и первого handshake с объяснением: связь с сервером не равна проверенному интернету.
2. Управление выданными конфигами: дата выдачи/изменения, напоминание об обновлении устройства; не обещать автоматическую доставку.
3. MFA/TOTP и отдельные операторские учётные записи с отзывом сессий; отдельный проект с recovery-кодами и тестами, не добавлять поспешно.
4. Настоящий серверный журнал действий без ключей и конфигов; объяснять источник и срок хранения.
5. Понятный мастер подключения по типу приложения/устройства, проверка совместимости AWG и инструкции по защите при обрыве.
6. Полная русская терминология вместо CANARY/peer/read-back; ясные состояния и время последнего обновления, доступность с клавиатуры.
7. Безопасный dual-stack перенос подсети с preview изменений и восстановлением; до реализации действие закрыто.
8. Политика индивидуальных профилей/отзыва и сроков доступа. Публичные ссылки на бессрочные конфиги не добавлять по умолчанию.

Идеи сверены по первичным источникам: https://github.com/wg-easy/wg-easy (2FA, сроки клиентов), https://docs.wgdashboard.dev/features/ (TOTP, организация клиентов, диагностика), https://docs.amnezia.org/documentation/instructions/killswitch/ (клиентская защита), https://wiresock.net/documentation/wiresock-secure-connect/network-settings.html (режимы WireSock). Идеи используются для сравнения; чужой код и оформление не копировались.

## Серверный журнал — установлен и проверен
- Добавлен GET /api/actions: действующая операторская сессия, лимит чтения, последние 200 записей, без nonce_digest и исходных строк. Read-only режим не открывает этот API.
- Чтение проверяет права, владельца, inode, отсутствие подмены ссылкой и корректность всех строк в ограниченном файле. При ошибке возвращается нейтральный код без содержимого журнала.
- Панель показывает серверный источник, понятные русские операции, запрос отдельно от подтверждённого результата и предупреждение о непоказанных ранних записях. История состояния вкладки явно отделена от серверного журнала.
- Недоступность журнала не скрывает клиентов; экспорт недоступного журнала выключен. Локальные действия интерфейса не выдаются за серверные события.
- Проверки: Windows 213 тестов, 53 платформенных skips, без ошибок; GitHub Actions Linux CI для d8d5257 прошёл на Python 3.11, 3.12 и 3.13 по 213 тестов на job с 12 root-fixture skips; все восемь browser-сценариев успешно. Public safety (90 файлов), Git history safety, JS syntax, diff check — PASS.
- Первые Linux-прогоны выявили неполноту временного тестового комплекта; после добавления статических файлов и служебного wrapper полный выбранный набор прошёл. Активная версия при тестировании не менялась.
- Составной release `d8d5257-runtime-20261106` установлен в `/opt/awg-cita/current`. Старый release `privacy-20261106` сохранён для rollback. Перезапущены только `awg-cita` и `awg-cita-rate-limit`.
- Дальше: понятные состояния подключения и давность данных, мастер подключения, отдельная работа над MFA и клиентскими утечками. Проверка интернет-доступа и защиты при обрыве не заменяется чтением handshake.


## Финальный preflight составного кандидата 2026-11-06
- Production переключён на утверждённый runtime release. Authenticated `/api/actions` отвечает 200.
- Сравнение production-файлов с родителем и `d8d5257` завершено. Все файлы совпадают с одним из вариантов, кроме смешанного `sector-console.js`; его diff объяснён ранее установленным privacy-блоком и добавлениями journal API.
- Выбран составной выпуск целиком. Чистый journal-only frontend не выделялся.
- Wheel повторно собран из чистого `git archive` commit с `SOURCE_DATE_EPOCH=1793970187`. Стабильная checksum `9423679c5e612292e0469cca610afad2a2b082a0dbd7e00079fef1825e1113f9`, размер 128244 байта. Предыдущая checksum `6d608d4...` относится к рабочей копии и больше не является актуальной.
- Runtime-манифест сохранён в `reports/AWG-CITA_runtime_manifest_2026-11-06.md`.
- `awg-cita-profile-write.conf` в runtime-релиз не включён. Нужный privacy/migration drop-in уже присутствует на host и не является зависимостью API журнала.
- Frontend preflight подтвердил таймеры и очистку приватных данных, очистку после 401 и скрытия страницы, защиту поздних ответов, сохранение черновиков, server_audit, `/api/actions`, truncated, отдельную историю вкладки и отключение экспорта при ошибке журнала.
- Browser preflight: 8 сценариев PASS. Targeted Python: 61 PASS, 30 platform skips. Full Windows Python: 213 PASS, 53 platform skips.
- POSIX writer, symlink/path replacement, fsync failure latch, external growth, Unix sockets, HTTP/CLI audit contracts и root-dependent проверки подтверждены отдельным root GitHub Actions gate.

## Root POSIX gate 2026-11-06
- Отдельный CI run `42264052052` успешно завершён на GitHub-hosted Ubuntu.
- Workflow checkout-ит commit `d8d5257461cc31d9ef715396fba01fc7d11660dd` и запускает полный suite через `sudo -n`.
- Результат: 213 тестов, 0 failures, 0 errors. Root-owned files, root-owned atomic semantics и isolated Linux root fixture выполнены без skips.
- Подтверждены `test_protected_profile_requires_root_owned_private_file`, `test_atomic_update_readback_and_rollback`, `test_socket_owner_mode_and_close_cleanup`, action audit fsync/external append/symlink/path replacement и HTTP audit failure-latch tests.
- Workflow добавлен только во временную ветку `codex/root-posix-gate-20261106`. Код приложения, production и основной кандидат не изменялись.
- Runtime manifest и preflight состав не менялись.
- После установки выполнены post-install проверки. Статус release `DEPLOYED_AND_VERIFIED`.

## Финальный статус

DEPLOYED_AND_VERIFIED

## Deployment verification 2026-11-06
- Active release: `/opt/awg-cita/releases/d8d5257-runtime-20261106`.
- Previous release `/opt/awg-cita/releases/privacy-20261106` retained.
- `awg-cita` and `awg-cita-rate-limit` are active/running.
- Backend and relay Unix sockets are ready.
- Authenticated backend `GET /` returned 200.
- Authenticated `GET /api/actions` returned 200, 108 events, `truncated=false`.
- API response contained no `nonce_digest`, keys, endpoint, routes, QR or configuration markers.
- Client counts unchanged: AWG3 6, AWG2 12, WireGuard 124.
- VPN configuration files and peer sets unchanged.
- Disposable canary mutation was not run because it requires separate approval.
- No VPN, client, firewall, NAT, route, DNS or operator-auth changes were made.

## DE-2 preflight and SSH diagnosis 2026-11-07

- Host `DE2_ADDRESS` identifies as `DE-2`.
- `/opt/awg-cita/current` points to `/opt/awg-cita/releases/564b0281`, which is the parent runtime, not `d8d5257-runtime-20261106`.
- `awg-cita.service` and `awg-cita-rate-limit.service` are absent from systemd. Both commands report `inactive`, and their journal has no entries.
- `/run/awg-cita-relay/relay.sock` and `/run/awg-cita-app/backend.sock` are dangling symlinks. Caddy is configured to proxy the panel to the relay socket, so the panel backend is unavailable. This explains the DE-2 panel error and the missing journal API.
- Caddy is listening on ports 80 and 443. `sshd` is listening on `0.0.0.0:22` and `[::]:22`.
- The new SSH key is present once in `/root/.ssh/authorized_keys`. The directory is `root:root` mode `700`, and the file is `root:root` mode `600`.
- Windows routes the DE-2 address through VPNUS. The earlier `WinError 10013` was observed in a network-restricted process and does not establish a VPNUS/WFP fault. On 2026-11-08 the pinned DE-2 SSH handshake succeeded outside those process restrictions, but public-key authentication was rejected. No DE-2 network/root-cause attribution is made from the earlier failure.
- No VPN, client, firewall, NAT, route, DNS or operator-auth changes were made during this diagnosis.

## DE-2 bootstrap compatibility gate 2026-11-07

- Read-only baseline оформлен в `reports/AWG-CITA_DE2_bootstrap_preflight_2026-11-07.md`.
- DE-2 остаётся на `/opt/awg-cita/releases/564b0281`; target `d8d5257-runtime-20261106` не установлен.
- На DE-2 отсутствуют `awg-cita.service`, `awg-cita-rate-limit.service`, рабочие backend/relay listeners и обязательные wrapper/helper-пути `/usr/local/bin/awg-cita-read`, `/usr/local/bin/awg`, `/usr/local/sbin/awg-manager-read`, `/usr/local/sbin/awg-cita-peer`, `/usr/local/sbin/awg-cita-profile`.
- `python3` доступен, но системные `pip` и `wheel` отсутствуют; одного versioned AWG binary недостаточно для проверенной схемы SE1.
- Выкладка, переключение symlink, daemon-reload и перезапуски на DE-2 не выполнялись. VPN, клиенты, firewall, NAT, маршруты, DNS, SSH и operator auth не изменялись.
- Rollback не потребовался; текущий release `564b0281` сохранён.
- Post-install проверки DE-2 не выполнены, потому что bootstrap остановлен до первой production-записи.

### Статус DE-2

`DE2_BLOCKED`

Разблокировка требует подтверждённого bootstrap helper-команд с SHA/владельцами, затем отдельного rollback bundle и повторного полного preflight. SE1 не изменён.

## Deployment bundle inventory 2026-11-07

- Отчёт сохранён в `reports/AWG-CITA_deployment_bundle_inventory_2026-11-07.md`.
- Историческое состояние на 2026-11-07: live inventory не был завершён из-за `WinError 10013` ограниченного процесса. Обновление 2026-11-08: SSH к SE1 через VPNUS работает, inventory получен; причина не была доказана как VPNUS/WFP.
- В репозитории есть tracked AWG-CITA scripts и application runtime, но отсутствуют исходники/manifest для `awg-cita-read`, `awg-manager-read`, systemd units, Caddy drop-in и внешнего AWG binary.
- Исторические `.ops-tmp`-скрипты не считаются текущим production inventory и не добавлялись в bundle.
- Отдельная Git-ветка не создана: локальный `.git` вернул `Permission denied` при создании ref.
- Clean-host bootstrap не запускался; DE-2 и SE1 не изменялись.

### Deployment bundle status

`BLOCKED`

## SE1 SSH и live inventory — 2026-11-08

- SSH к `SE1_ADDRESS` успешно работает через включённый VPNUS с source address `VPNUS_SOURCE`; закреплённый fingerprint совпал, авторизация существующим ключом успешна.
- Прежняя атрибуция `WinError 10013` фильтру VPNUS/WFP отозвана: та же команда работает вне сетевых ограничений процесса выполнения. Для SE1 доказана проблема ограниченного процесса, а не VPNUS. Причина прежних ошибок DE-2 этим не установлена.
- Разрешённый временный Windows `/32` route проверен и удалён; дополнительного маршрута не осталось. VPNUS продолжает работать. Серверные изменения не выполнялись.
- Получены live размеры, SHA256, owner/group/mode units, helpers, drop-ins, sudoers, runtime и sockets. Исходники пяти helper/wrapper-команд прочитаны без извлечения secrets/client configs.
- SE1: Ubuntu 24.04.4 x86_64; Python 3.12.3; segno 1.6.6; bcrypt 3.2.2; обе веб-службы и Caddy active/running; current — `d8d5257-runtime-20261106`.
- AWG binary SHA256 `a604430b4b85e1cfb2e5a9fbd3ca0219e5cd1a0a0173243c0a4201332b522d28`; `--version` сообщает `v3.1.20260812`, каталог называется `3.1.20260828`. Upstream/source/license/build origin ещё требуется проверить.
- Новый отчёт: `reports/AWG-CITA_SE1_live_inventory_2026-11-08.md`. Вывод о недоступности SE1 в предыдущем отчёте устарел. Bundle остаётся `BLOCKED` до provenance и clean-host проверки; DE-2 не изменён.
