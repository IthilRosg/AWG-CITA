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

## Deployment bundle и DE-2 — итог 2026-11-08

**Deployment bundle: `DEPLOYMENT_BUNDLE_READY`. DE-2: `DEPLOYED_AND_VERIFIED`.**

- Приложение неизменно: `d8d5257461cc31d9ef715396fba01fc7d11660dd`.
- Проверенная и установленная deployment-ревизия: `fe8682434f22c230f897aca1124d8b5aa83f6e24`, ветка `codex/deployment-bundle-20261108`. Последующие изменения этого статуса относятся только к документации.
- В репозиторий включены проверенные шаблоны units, read/helpers, узкие sudoers, установщик/preflight/verify/rollback, dependency locks, сборка manifest и clean-host systemd CI. Неизвестные host binaries, секреты, журналы и VPN-конфиги не публиковались.
- Новый manifest v2 сформирован отдельно; прежний application-only manifest сохранён. 72 runtime-файла, SHA256 manifest `1d8aaa0130e04517fe5b4121a3bf1211c614a12f81b42af63390d45ac4758ccc`. Локальный комплект: `artifacts/deployment-fe86824/de2-bundle/`.
- Clean-host Ubuntu 24.04/systemd CI прошёл для обеих схем units, standard и legacy: https://github.com/IthilRosg/AWG-CITA/actions/runs/42462326024 . Полные Python/browser/public-safety проверки той же ревизии прошли: https://github.com/IthilRosg/AWG-CITA/actions/runs/42462326028 .
- CI проверяет настоящий bcrypt-вход через Caddy, права сервисного пользователя, helpers, authenticated API, повторную установку, sockets, сохранение файлов и rollback до/после current. AWG fixture отделён от проверки настоящего upstream binary; kernel/tunnel bootstrap не заявляется.
- Опубликован закреплённый пакет offline wheels: https://github.com/IthilRosg/AWG-CITA/releases/tag/panel-deployment-fe86824 . Это приложение и две Python-зависимости; AWG, host-конфиг и секреты туда не входят.

### Исправление прежнего inventory DE-2

Прежние утверждения об отсутствии всей панели и dangling sockets отозваны. До установки действовали `awg-cita-app.service` и `awg-cita-relay.service`, рабочие Unix sockets и большинство helpers. Отсутствовал `awg-cita-read`. Совместимость проверена по фактической legacy-схеме; она сохранена. До установки current указывал на `564b0281`, а не на runtime SE1. UI содержит 2/7/1 клиента, live peers 2/6/1: один AWG2-клиент отключён.

### Установка и live acceptance DE-2

- После preflight и проверки SHA комплект установлен через root VNC. Current: `/opt/awg-cita/releases/d8d5257-runtime-20261106-deploy-8e33e208bfb8`. Предыдущий release `564b0281` сохранён.
- Перезапущена только фактическая пара веб-служб `awg-cita-app`/`awg-cita-relay`; обе active и enabled. Сокеты созданы службами, их владельцы и права проверены. Caddy active, его конфигурация побайтно прежняя, restart/reload Caddy не выполнялся.
- Пользователь вошёл прежними реквизитами. GET / и authenticated GET /api/actions успешны. `source=server_audit`, 96 событий, 48 INTENT и 48 RESULT, `truncated=false`. Поля строго: actor, checked_at, client_id, correlation_id, operation, phase, result. nonce_digest и секретные маркеры отсутствуют.
- Списки UI: AWG3 2, AWG2 7 (один отключён), WireGuard 1. SHA VPN-файлов, профилей, девяти сохранённых клиентских конфигов и auth-файла совпали с исходными; live peer sets совпали. Оба журнала сохраняют прежние байты как префикс.
- Для DE-2 сохранена отдельная transaction backup в `/var/backups/awg-cita-deployment/`; точный путь и команда отката приведены в локальном итоговом отчёте. Production rollback не потребовался; сценарии проверены в изолированном CI. Журналы при откате сохраняются.
- VPN, клиенты, firewall, NAT, маршруты, DNS, SSH и операторские реквизиты не изменялись. Rescue/canary mutation не выполнялась.

### SE1 и сетевой диагноз

- SE1 использован только для чтения. Свежая итоговая проверка: прежний `d8d5257-runtime-20261106`, обе веб-службы active, GET / и authenticated /api/actions 200, 108 событий, truncated=false, nonce_digest отсутствует. Клиенты 6/12/124.
- SSH к SE1 работает через включённый VPNUS с закреплённой идентичностью. Прежняя атрибуция WinError 10013 VPNUS/WFP отозвана: для SE1 подтверждено ограничение процесса выполнения. Временный Windows /32 маршрут удалён, VPNUS остаётся включённым.
- DE-2 SSH handshake вне ограничения процесса успешен, но проверенные ключи отвергнуты. Причина прежнего отказа не объявляется установленной; SSH не изменялся и не являлся каналом установки.

### Ограничения и следующий этап

- Действующий AWG оставлен на месте с host-specific SHA и проверкой версии/read-back. Его сборка не приписывается upstream prebuilt, поскольку SHA различаются. Для распространяемого внешнего artifact закреплены официальный source/tag/commit, license и SHA.
- Для нового хоста существующие VPN-профили, совместимый AWG, Caddy/origin/group access и реквизиты — явные prerequisites. Установщик не является установщиком VPN или провайдером credentials.
- Сквозное VPN-подключение, DNS/IPv6/kill-switch, мутации клиентов и production canary здесь не проверялись. Root/POSIX и failure-latch приложения подтверждены ранее; новый clean-host gate подтверждает deployment.
- Подробный локальный отчёт: `reports/AWG-CITA_deployment_DE2_result_2026-11-08.md`; manifest по каждому файлу — `reports/AWG-CITA_deployment_manifest_v2_DE2_2026-11-08.md`.

Оставшихся блокеров согласованного deployment-этапа нет. Следующие изменения приложения требуют отдельного scope; текущая задача завершена работающей и проверенной панелью DE-2.
