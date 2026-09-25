"""Generic AWG CITA operator-console HTML shell.

The page is intentionally a static shell. Product behavior lives in the
browser-side mock adapter and can later be connected to a reviewed lifecycle
contract without changing the visual shell.
"""

INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0c0c0d">
  <title>AWG CITA · Sector Console</title>
  <link rel="icon" href="/static/sector-console.svg" type="image/svg+xml">
  <link rel="stylesheet" href="/static/sector-console.css">
</head>
<body>
  <div class="shell" data-runtime="mock_lifecycle">
    <aside class="rail" aria-label="AWG CITA navigation">
      <div class="brand"><span class="brand-mark">◇</span> AWG CITA</div>
      <div class="rail-caption" data-i18n="consoleLabel">ОПЕРАТОРСКАЯ КОНСОЛЬ</div>
      <nav class="nav" aria-label="Primary navigation">
        <button class="nav-item is-active" type="button" data-view="overview" aria-current="page">
          <span class="nav-index">01</span>
          <span data-i18n="navOverview">Обзор</span>
        </button>
        <button class="nav-item" type="button" data-view="clients" aria-current="false">
          <span class="nav-index">02</span>
          <span data-i18n="navClients">Клиенты</span>
        </button>
        <button class="nav-item" type="button" data-view="journal" aria-current="false">
          <span class="nav-index">03</span>
          <span data-i18n="navJournal">Журнал</span>
        </button>
        <button class="nav-item" type="button" data-view="settings" aria-current="false">
          <span class="nav-index">04</span>
          <span data-i18n="navSettings">Профили</span>
        </button>
      </nav>
      <div class="rail-status">
        <span class="signal-dot" aria-hidden="true"></span>
        <div>
          <strong data-i18n="mockBoundary">UI READY / BACKEND STUB</strong>
          <small data-i18n="railBoundary">Мутации отключены</small>
        </div>
      </div>
    </aside>

    <main id="app" class="app" aria-busy="true">
      <div class="topbar">
        <span class="eyebrow" data-i18n="perimeter">ЛОКАЛЬНЫЙ КОНТУР</span>
        <span id="connection-state" class="connection-state" data-state="loading">● LOADING</span>
      </div>

      <header class="page-header">
        <div class="page-heading">
          <div class="eyebrow" data-i18n="summaryEyebrow">01 — СВОДКА</div>
          <h1>
            <span data-i18n="titleLineOne">Узел</span>
            <span data-i18n="titleLineTwo">управления</span>
          </h1>
          <p class="page-subtitle" data-i18n="subtitle">Безопасная operator telemetry для AmneziaWG.</p>
        </div>
        <div class="header-actions">
          <div class="language-menu">
            <button id="language-toggle" class="button button-quiet" type="button" aria-haspopup="menu" aria-expanded="false">RU ▾</button>
            <div id="language-list" class="language-list" role="menu" hidden>
              <button type="button" role="menuitem" data-lang="ru">Русский</button>
              <button type="button" role="menuitem" data-lang="en">English</button>
            </div>
          </div>
          <button id="refresh-button" class="button" type="button" data-i18n="refresh">Обновить</button>
          <button id="add-client-button" class="button button-primary" type="button" aria-describedby="mutation-boundary" data-i18n="addClient">Создать preview</button>
        </div>
      </header>

      <div id="mutation-boundary" class="boundary-note" data-i18n="mutationBoundary">Live lifecycle mutations отключены; эта кнопка открывает только preview.</div>
      <div id="global-error" class="notice notice-error" role="alert" hidden></div>

      <div id="create-preview-modal" class="modal-backdrop" role="presentation" hidden aria-hidden="true">
        <section class="modal-dialog panel" role="dialog" aria-modal="true" aria-labelledby="preview-dialog-title" aria-describedby="preview-dialog-copy">
          <div class="modal-heading">
            <div>
              <div class="eyebrow" data-i18n="previewEyebrow">CONTROLLED LIFECYCLE / PREVIEW</div>
              <h2 id="preview-dialog-title" data-i18n="previewDialogTitle">Создание клиента · preview</h2>
            </div>
            <button id="preview-close" class="icon-button" type="button" data-i18n-label="closePreview" aria-label="Закрыть preview">×</button>
          </div>
          <p id="preview-dialog-copy" class="modal-copy" data-i18n="previewDialogCopy">Проверка метаданных без создания peer, ключей, конфигурации или QR.</p>

          <div id="preview-step-form" class="preview-step">
            <div class="preview-step-label" data-i18n="previewStepDetails">Данные клиента</div>
            <label class="form-field" for="preview-name">
              <span data-i18n="previewNameLabel">Имя клиента</span>
              <input id="preview-name" type="text" maxlength="48" autocomplete="off" data-i18n-placeholder="previewNamePlaceholder" placeholder="Например, Field Laptop">
              <small data-i18n="previewNameHint">2–48 символов: буквы, цифры, пробел, точка, дефис или подчёркивание.</small>
            </label>
            <label class="form-field" for="preview-tags">
              <span data-i18n="previewTagsLabel">Tags · необязательно</span>
              <input id="preview-tags" type="text" maxlength="140" autocomplete="off" data-i18n-placeholder="previewTagsPlaceholder" placeholder="field, review">
              <small data-i18n="previewTagsHint">До 5 tags через запятую, без секретов и connection data.</small>
            </label>
            <div id="preview-form-error" class="notice notice-error" role="alert" hidden></div>
          </div>

          <div id="preview-step-result" class="preview-step" hidden>
            <div class="preview-step-label" data-i18n="previewStepResult">Результат / Dry run</div>
            <h3 data-i18n="previewResultHeading">Preview принят</h3>
            <p class="modal-copy" data-i18n="previewResultCopy">Mock adapter проверил безопасные метаданные. Production lifecycle не вызывался.</p>
            <dl class="preview-result-list">
              <div><dt data-i18n="previewResultId">Preview ID</dt><dd id="preview-result-id" class="mono">—</dd></div>
              <div><dt data-i18n="previewResultName">Имя</dt><dd id="preview-result-name">—</dd></div>
              <div><dt data-i18n="previewResultTags">Tags</dt><dd id="preview-result-tags">—</dd></div>
              <div><dt data-i18n="previewResultStatus">Статус</dt><dd id="preview-result-status" class="mono">DRY_RUN</dd></div>
            </dl>
            <div id="preview-result-boundary" class="preview-boundary" data-i18n="previewNoPeerCreated">NO PEER CREATED · KEYS / CONFIG / QR NOT GENERATED</div>
            <div id="create-real-result" hidden>
              <div class="create-result-actions">
                <button id="create-config-download" class="button button-primary" type="button">Download .conf</button>
                <button id="create-config-copy" class="button" type="button">Copy configuration</button>
              </div>
              <details class="config-disclosure"><summary id="create-qr-summary">Показать QR</summary>
                <div class="create-qr-wrap"><canvas id="create-qr" role="img" aria-label="Client configuration QR · private" width="220" height="220"></canvas></div>
                <p id="create-qr-caption" class="modal-copy">QR contains the private .conf for compatible scanners.</p>
              </details>
              <details class="config-disclosure"><summary id="create-text-summary">Показать текст .conf</summary>
                <label class="form-field" for="create-config-text"><span>Configuration · private</span>
                  <textarea id="create-config-text" readonly spellcheck="false" autocomplete="off" rows="8"></textarea>
                </label>
              </details>
            </div>
          </div>

          <div class="modal-actions">
            <button id="preview-cancel" class="button button-quiet" type="button" data-i18n="previewCancel">Отмена</button>
            <button id="preview-submit" class="button button-primary" type="button" data-i18n="previewSubmit">Запустить preview</button>
            <button id="preview-done" class="button button-primary" type="button" data-i18n="previewDone" hidden>Готово</button>
          </div>
        </section>
      </div>

      <div id="edit-client-modal" class="modal-backdrop" data-dialog="edit" role="presentation" hidden aria-hidden="true">
        <section class="modal-dialog panel" role="dialog" aria-modal="true" aria-labelledby="edit-dialog-title" aria-describedby="edit-dialog-copy">
          <div class="modal-heading">
            <div>
              <div class="eyebrow" data-i18n="editEyebrow">CLIENT METADATA / MOCK</div>
              <h2 id="edit-dialog-title" data-i18n="editDialogTitle">Редактировать клиента</h2>
            </div>
            <button id="edit-close" class="icon-button" type="button" data-i18n-label="closeEdit" aria-label="Закрыть редактирование">×</button>
          </div>
          <p id="edit-dialog-copy" class="modal-copy" data-i18n="editDialogCopy">Изменения применяются только к frontend mock state и записываются в Journal.</p>
          <div class="preview-step">
            <label class="form-field" for="edit-name">
              <span data-i18n="editNameLabel">Имя клиента</span>
              <input id="edit-name" type="text" maxlength="48" autocomplete="off">
            </label>
            <label class="form-field" for="edit-notes">
              <span data-i18n="editNotesLabel">Notes</span>
              <textarea id="edit-notes" maxlength="240" rows="4"></textarea>
            </label>
            <label class="form-field" for="edit-tags">
              <span data-i18n="editTagsLabel">Tags</span>
              <input id="edit-tags" type="text" maxlength="140" autocomplete="off" data-i18n-placeholder="editTagsPlaceholder" placeholder="priority, review">
            </label>
            <label class="form-field" for="edit-expiration">
              <span data-i18n="editExpirationLabel">Истекает</span>
              <input id="edit-expiration" type="date">
            </label>
            <div id="edit-form-error" class="notice notice-error" role="alert" hidden></div>
          </div>
          <div class="modal-actions">
            <button id="edit-cancel" class="button button-quiet" type="button" data-i18n="cancel">Отмена</button>
            <button id="edit-save" class="button button-primary" type="button" data-i18n="saveChanges">Сохранить изменения</button>
          </div>
        </section>
      </div>

      <div id="delete-client-modal" class="modal-backdrop" data-dialog="delete" role="presentation" hidden aria-hidden="true">
        <section class="modal-dialog modal-dialog-danger panel" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-copy">
          <div class="modal-heading">
            <div>
              <div class="eyebrow" data-i18n="deleteEyebrow">DESTRUCTIVE ACTION / MOCK</div>
              <h2 id="delete-dialog-title" data-i18n="deleteDialogTitle">Удалить клиента?</h2>
            </div>
            <button id="delete-close" class="icon-button" type="button" data-i18n-label="closeDelete" aria-label="Закрыть удаление">×</button>
          </div>
          <p id="delete-dialog-copy" class="modal-copy" data-i18n="deleteDialogCopy">Проверьте имя клиента и подтвердите удаление только из frontend mock state.</p>
          <div class="preview-step">
            <div class="destructive-summary">
              <span data-i18n="selectedClient">Клиент</span>
              <strong id="delete-client-name">—</strong>
            </div>
            <div class="preview-boundary preview-boundary-danger" data-i18n="deleteBoundary">Peer, ключи и production state не удаляются.</div>
          </div>
          <div class="modal-actions">
            <button id="delete-cancel" class="button button-quiet" type="button" data-i18n="cancel">Отмена</button>
            <button id="delete-confirm" class="button button-danger" type="button" data-i18n="deleteConfirm">Удалить mock record</button>
          </div>
        </section>
      </div>

      <div id="config-preview-modal" class="modal-backdrop" data-dialog="config" role="presentation" hidden aria-hidden="true">
        <section class="modal-dialog panel" role="dialog" aria-modal="true" aria-labelledby="config-preview-title" aria-describedby="config-preview-copy-text">
          <div class="modal-heading">
            <div>
              <div class="eyebrow" data-i18n="configEyebrow">CONFIGURATION / MOCK PREVIEW</div>
              <h2 id="config-preview-title" data-i18n="configDialogTitle">Конфигурация клиента · preview</h2>
            </div>
            <button id="config-preview-close" class="icon-button" type="button" data-i18n-label="closeConfig" aria-label="Закрыть preview конфигурации">×</button>
          </div>
          <p id="config-preview-copy-text" class="modal-copy" data-i18n="configDialogCopy">Показаны только синтетические QR и configuration placeholders. Реальные секреты не генерируются.</p>
          <div class="preview-step config-preview-body">
            <div class="config-preview-summary">
              <div><span data-i18n="selectedClient">Клиент</span><strong id="config-preview-name">—</strong></div>
              <div><span data-i18n="expiration">Истекает</span><strong id="config-preview-expiration">—</strong></div>
              <div><span data-i18n="previewResultStatus">Статус</span><strong id="config-preview-status" class="mono">MOCK_PREVIEW</strong></div>
            </div>
            <div class="preview-boundary" data-i18n="configBoundary">UI READY / BACKEND STUB · MOCK DATA ONLY</div>
            <div class="config-tabs" role="tablist" aria-label="Configuration preview format">
              <button id="config-preview-tab-qr" class="config-tab is-active" type="button" role="tab" aria-selected="true" aria-controls="config-preview-qr-panel" data-config-tab="qr" data-i18n="configQrTab">QR</button>
              <button id="config-preview-tab-config" class="config-tab" type="button" role="tab" aria-selected="false" aria-controls="config-preview-config-panel" data-config-tab="config" data-i18n="configTextTab">CONFIG</button>
              <button id="config-preview-tab-edit" class="config-tab" type="button" role="tab" aria-selected="false" aria-controls="config-preview-edit-panel" data-config-tab="edit" hidden>Параметры</button>
            </div>
            <section id="config-preview-qr-panel" class="config-tab-panel" role="tabpanel" aria-labelledby="config-preview-tab-qr">
              <div id="config-preview-qr" class="mock-qr" role="img" aria-label="Mock QR preview"><span>MOCK QR</span></div>
              <code id="config-preview-qr-payload" class="mock-payload">—</code>
              <small class="config-sensitive-note" data-i18n="configSensitiveNote">В production configuration будет sensitive material; в этом prototype оно не создаётся.</small>
            </section>
            <section id="config-preview-config-panel" class="config-tab-panel" role="tabpanel" aria-labelledby="config-preview-tab-config" hidden>
              <pre id="config-preview-text" class="mock-config"># MOCK CONFIGURATION</pre>
            </section>
            <section id="config-preview-edit-panel" class="config-tab-panel" role="tabpanel" aria-labelledby="config-preview-tab-edit" hidden>
              <p id="config-edit-intro" class="modal-copy">Изменения сохраняются для повторной выдачи этого клиента. Ключи и параметры сервера не меняются.</p>
              <form id="config-edit-form" class="config-edit-grid">
                <label>DNS <input name="dns_server" type="text" autocomplete="off" required></label>
                <label>AllowedIPs <input name="allowed_ips" type="text" autocomplete="off" required></label>
                <label>MTU <input name="mtu" type="number" min="1280" max="1500" required></label>
                <label>Keepalive <input name="keepalive" type="number" min="0" max="120" required></label>
                <div id="config-edit-status" role="status"></div>
                <button id="config-edit-save" class="button button-primary" type="submit">Сохранить параметры</button>
              </form>
            </section>
          </div>
          <div class="modal-actions">
            <button id="config-preview-download" class="button button-primary" type="button" data-i18n="downloadMock">Скачать mock</button>
            <button id="config-preview-copy" class="button" type="button" data-i18n="copyConfig">Копировать</button>
            <button id="config-preview-close-action" class="button button-quiet" type="button" data-i18n="close">Закрыть</button>
          </div>
        </section>
      </div>

      <div id="client-actions-menu" class="row-actions-menu" role="menu" aria-label="Client actions" hidden aria-hidden="true">
        <button id="client-action-open" class="row-action-item" type="button" role="menuitem" data-client-action="open" data-i18n="actionOpen">Открыть</button>
        <button id="client-action-edit" class="row-action-item" type="button" role="menuitem" data-client-action="edit" data-i18n="actionEdit">Редактировать metadata</button>
        <button id="client-action-config" class="row-action-item" type="button" role="menuitem" data-client-action="config" data-i18n="actionConfig">Сформировать configuration</button>
        <button id="client-action-disable" class="row-action-item" type="button" role="menuitem" data-client-action="disable" data-i18n="actionDisable">Отключить</button>
        <button id="client-action-enable" class="row-action-item" type="button" role="menuitem" data-client-action="enable" data-i18n="actionEnable" hidden>Включить</button>
        <button id="client-action-delete" class="row-action-item row-action-danger" type="button" role="menuitem" data-client-action="delete" data-i18n="actionDelete">Удалить</button>
      </div>

      <section id="overview-view" class="view" data-view-panel="overview" aria-labelledby="overview-heading">
        <div class="section-heading">
          <div>
            <div class="eyebrow" data-i18n="overviewEyebrow">01 / OVERVIEW</div>
            <h2 id="overview-heading" data-i18n="overviewHeading">Состояние узла</h2>
          </div>
          <div class="refresh-meta">
            <span data-i18n="lastRefresh">Последнее обновление</span>
            <strong id="last-refresh">—</strong>
          </div>
        </div>

        <div class="metrics" aria-label="Overview metrics">
          <article class="metric-card">
            <span class="metric-label" data-i18n="state">Состояние</span>
            <strong id="metric-state" class="metric-value">—</strong>
            <small data-i18n="stateDescription">frontend state готов</small>
          </article>
          <article class="metric-card">
            <span class="metric-label" data-i18n="active">Активны</span>
            <strong id="metric-online" class="metric-value">—</strong>
            <small id="metric-online-detail">—</small>
          </article>
          <article class="metric-card">
            <span class="metric-label" data-i18n="traffic">Трафик сессии</span>
            <strong id="metric-traffic" class="metric-value">—</strong>
            <small data-i18n="trafficDescription">RX + TX по fixture dataset</small>
          </article>
          <article class="metric-card metric-card-alert">
            <span class="metric-label" data-i18n="attention">Внимание</span>
            <strong id="metric-attention" class="metric-value">—</strong>
            <small data-i18n="attentionDescription">stale / never / disabled</small>
          </article>
        </div>

        <div class="overview-grid">
          <section class="panel activity-panel" aria-labelledby="activity-heading">
            <div class="panel-heading">
              <div>
                <div class="eyebrow" data-i18n="activityEyebrow">EVENT STREAM</div>
                <h3 id="activity-heading" data-i18n="activityHeading">Журнал активности</h3>
              </div>
              <span class="panel-count" id="activity-count">0</span>
            </div>
            <div id="activity-list" class="activity-list"></div>
          </section>
          <section class="panel health-panel" aria-labelledby="health-heading">
            <div class="panel-heading">
              <div>
                <div class="eyebrow" data-i18n="healthEyebrow">CONTROL PLANE</div>
                <h3 id="health-heading" data-i18n="healthHeading">Сигналы состояния</h3>
              </div>
              <span class="health-mark" aria-hidden="true">◎</span>
            </div>
            <dl class="health-list">
              <div><dt data-i18n="totalPeers">Всего клиентов</dt><dd id="health-total">—</dd></div>
              <div><dt data-i18n="onlinePeers">Online</dt><dd id="health-online">—</dd></div>
              <div><dt data-i18n="disabledPeers">Disabled</dt><dd id="health-disabled">—</dd></div>
              <div><dt data-i18n="stalePeers">Stale</dt><dd id="health-stale">—</dd></div>
              <div><dt data-i18n="attentionPeers">Требуют внимания</dt><dd id="health-attention">—</dd></div>
              <div><dt data-i18n="adapterMode">Adapter</dt><dd data-i18n="adapterMock">MOCK LIFECYCLE</dd></div>
            </dl>
          </section>
        </div>
      </section>

      <section id="clients-view" class="view" data-view-panel="clients" aria-labelledby="clients-heading" hidden>
        <div class="section-heading">
          <div>
            <div class="eyebrow" data-i18n="clientsEyebrow">02 / REGISTRY</div>
            <h2 id="clients-heading" data-i18n="clientsHeading">Реестр клиентов</h2>
            <p class="section-subtitle" data-i18n="clientsSubtitle">Поиск, фильтры и dossier работают поверх frontend state.</p>
          </div>
          <div class="result-summary"><strong id="client-count">—</strong><span data-i18n="records">записей</span></div>
        </div>

        <div class="profile-switch panel" role="group" aria-label="Connection profiles">
          <button class="profile-choice is-active" type="button" data-client-profile="awg3" aria-pressed="true">AWG 3.1</button>
          <button class="profile-choice" type="button" data-client-profile="awg2" aria-pressed="false">AWG 2.0 · WireSock</button>
          <button class="profile-choice" type="button" data-client-profile="wg" aria-pressed="false">WireGuard</button>
        </div>

        <div class="controls panel">
          <label class="search-field" for="client-search">
            <span class="eyebrow" data-i18n="searchLabel">ПОИСК</span>
            <span class="search-input-wrap">
              <span class="search-glyph" aria-hidden="true">⌕</span>
              <input id="client-search" type="search" autocomplete="off" data-i18n-placeholder="searchPlaceholder" placeholder="Имя, notes или tags">
              <button id="clear-search" class="clear-search" type="button" data-i18n-label="clearSearch" aria-label="Очистить поиск" hidden>×</button>
            </span>
          </label>
          <div class="filter-group">
            <div class="filter-heading">
              <span class="eyebrow" data-i18n="filterLabel">ФИЛЬТР</span>
              <button id="clear-filters" class="text-button" type="button" data-i18n="clearFilters" disabled>Сбросить</button>
            </div>
            <div class="status-filters" role="group" aria-label="Status filters">
              <button class="status-chip" type="button" data-status-filter="ONLINE" aria-pressed="false">ONLINE <span data-filter-count="ONLINE">0</span></button>
              <button class="status-chip" type="button" data-status-filter="IDLE" aria-pressed="false">IDLE <span data-filter-count="IDLE">0</span></button>
              <button class="status-chip" type="button" data-status-filter="STALE" aria-pressed="false">STALE <span data-filter-count="STALE">0</span></button>
              <button class="status-chip" type="button" data-status-filter="NEVER" aria-pressed="false">NEVER <span data-filter-count="NEVER">0</span></button>
              <button class="status-chip" type="button" data-status-filter="DISABLED" aria-pressed="false">DISABLED <span data-filter-count="DISABLED">0</span></button>
            </div>
          </div>
        </div>

        <div id="clients-empty" class="empty-panel" hidden>
          <div class="empty-mark" aria-hidden="true">∅</div>
          <h3 id="clients-empty-heading" data-i18n="noResultsHeading">Ничего не найдено</h3>
          <p id="clients-empty-copy" data-i18n="noResultsCopy">Измените поисковый запрос или сбросьте фильтры.</p>
          <button id="reset-empty" class="button" type="button" data-i18n="resetFilters">Сбросить фильтры</button>
        </div>

        <div class="client-layout">
          <section class="panel table-panel" aria-labelledby="table-heading">
            <div class="panel-heading table-heading">
              <div>
                <div class="eyebrow" data-i18n="tableEyebrow">PEER REGISTRY</div>
                <h3 id="table-heading" data-i18n="tableHeading">Клиенты</h3>
              </div>
              <span id="visible-count" class="panel-count">—</span>
            </div>
            <div class="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col" data-sort-col="name"><button class="sort-button" type="button" data-sort-key="name"><span data-i18n="clientColumn">Клиент</span><span class="sort-indicator" aria-hidden="true">↕</span></button></th>
                    <th scope="col" data-sort-col="status"><button class="sort-button" type="button" data-sort-key="status"><span data-i18n="statusColumn">Состояние</span><span class="sort-indicator" aria-hidden="true">↕</span></button></th>
                    <th scope="col" data-sort-col="handshake"><button class="sort-button" type="button" data-sort-key="handshake"><span data-i18n="handshakeColumn">Handshake</span><span class="sort-indicator" aria-hidden="true">↕</span></button></th>
                    <th scope="col" data-sort-col="lastSeen"><span data-i18n="lastActiveColumn">Последняя активность</span></th>
                    <th scope="col" data-sort-col="totalTraffic"><button class="sort-button" type="button" data-sort-key="totalTraffic"><span data-i18n="trafficColumn">Всего трафика</span><span class="sort-indicator" aria-hidden="true">↕</span></button></th>
                    <th scope="col" data-i18n="actionColumn">Действия</th>
                  </tr>
                </thead>
                <tbody id="client-rows"></tbody>
              </table>
            </div>
          </section>

          <aside id="client-dossier" class="panel dossier" aria-labelledby="dossier-heading" aria-hidden="true">
            <div class="panel-heading dossier-heading">
              <div>
                <div class="eyebrow" data-i18n="dossierEyebrow">SELECTED RECORD</div>
                <h3 id="dossier-heading" data-i18n="dossierHeading">Досье клиента</h3>
              </div>
              <button id="dossier-close" class="icon-button" type="button" data-i18n-label="closeDossier" aria-label="Закрыть досье">×</button>
            </div>
            <div id="dossier-empty" class="dossier-empty">
              <span class="dossier-mark" aria-hidden="true">◇</span>
              <strong data-i18n="dossierEmptyHeading">Клиент не выбран</strong>
              <span data-i18n="dossierEmptyCopy">Выберите строку, чтобы открыть dossier.</span>
            </div>
            <div id="dossier-content" hidden>
              <div class="dossier-title-row">
                <div>
                  <h4 id="dossier-client-name">—</h4>
                  <span id="dossier-client-id" class="mono muted">—</span>
                </div>
                <span id="dossier-status" class="status-pill">—</span>
              </div>
              <dl class="dossier-stats">
                <div><dt data-i18n="lastHandshake">Last handshake</dt><dd id="dossier-handshake">—</dd></div>
                <div><dt data-i18n="lastSeen">Last seen</dt><dd id="dossier-last-seen">—</dd></div>
                <div><dt data-i18n="createdAt">Создан</dt><dd id="dossier-created">—</dd></div>
                <div><dt data-i18n="expiration">Истекает</dt><dd id="dossier-expiration">—</dd></div>
              </dl>
              <div class="dossier-section">
                <div class="eyebrow" data-i18n="trafficSection">TRAFFIC</div>
                <div class="traffic-grid">
                  <div><span data-i18n="totalTraffic">Всего</span><strong id="dossier-total">—</strong></div>
                  <div><span data-i18n="received">Получено</span><strong id="dossier-rx">—</strong></div>
                  <div><span data-i18n="sent">Отправлено</span><strong id="dossier-tx">—</strong></div>
                </div>
              </div>
              <div class="dossier-section">
                <div class="eyebrow" data-i18n="metadataSection">METADATA</div>
                <div class="dossier-meta-row"><span data-i18n="notes">Notes</span><p id="dossier-notes">—</p></div>
                <div class="dossier-meta-row"><span data-i18n="tags">Tags</span><div id="dossier-tags" class="tag-list">—</div></div>
                <div class="dossier-meta-row"><span data-i18n="warnings">Warnings</span><p id="dossier-warning" class="warning-copy">—</p></div>
              </div>
              <div class="dossier-safe-note" data-i18n="safeNote">Keys, endpoints and raw AWG properties are not shown.</div>
              <button id="dossier-config-button" class="button button-block" type="button" data-dossier-action="config" data-i18n="configAction">Сформировать configuration · preview</button>
            </div>
          </aside>
        </div>
      </section>

      <section id="settings-view" class="view" data-view-panel="settings" aria-labelledby="settings-heading" hidden>
        <div class="section-heading"><div>
          <div class="eyebrow">04 / CONNECTION PROFILES</div>
          <h2 id="settings-heading" data-i18n="settingsHeading">Профили подключения</h2>
          <p class="section-subtitle" data-i18n="settingsSubtitle">Параметры ниже применяются только к новым конфигурациям клиентов.</p>
        </div></div>
        <div class="profile-settings-grid">
          <form class="panel profile-settings-card" data-template-profile="awg3">
            <div class="eyebrow">AWG 3.1 · awg-canary0</div><h3>AWG 3.1</h3>
            <label><span>DNS</span><input name="dns_server" autocomplete="off" required></label>
            <label><span>AllowedIPs · IPv4</span><input name="allowed_ips" autocomplete="off" required></label>
            <label><span>MTU</span><input name="mtu" type="number" min="1280" max="1500" required></label>
            <label><span>Keepalive</span><input name="keepalive" type="number" min="0" max="120" required></label>
            <div class="profile-settings-actions"><span data-template-status="awg3" role="status"></span><button class="button" type="submit" data-i18n="saveTemplate">Сохранить</button></div>
          </form>
          <form class="panel profile-settings-card" data-template-profile="awg2">
            <div class="eyebrow">AWG 2.0 · awg-cita2</div><h3>AWG 2.0 · WireSock</h3>
            <label><span>DNS</span><input name="dns_server" autocomplete="off" required></label>
            <label><span>AllowedIPs · IPv4</span><input name="allowed_ips" autocomplete="off" required></label>
            <label><span>MTU</span><input name="mtu" type="number" min="1280" max="1500" required></label>
            <label><span>Keepalive</span><input name="keepalive" type="number" min="0" max="120" required></label>
            <div class="profile-settings-actions"><span data-template-status="awg2" role="status"></span><button class="button" type="submit" data-i18n="saveTemplate">Сохранить</button></div>
          </form>
          <form class="panel profile-settings-card" data-template-profile="wg">
            <div class="eyebrow">WIREGUARD · awg-cita-wg</div><h3>WireGuard</h3>
            <label><span>DNS</span><input name="dns_server" autocomplete="off" required></label>
            <label><span>AllowedIPs · IPv4</span><input name="allowed_ips" autocomplete="off" required></label>
            <label><span>MTU</span><input name="mtu" type="number" min="1280" max="1500" required></label>
            <label><span>Keepalive</span><input name="keepalive" type="number" min="0" max="120" required></label>
            <div class="profile-settings-actions"><span data-template-status="wg" role="status"></span><button class="button" type="submit" data-i18n="saveTemplate">Сохранить</button></div>
          </form>
        </div>
      </section>

      <section id="journal-view" class="view" data-view-panel="journal" aria-labelledby="journal-heading" hidden>
        <div class="section-heading">
          <div>
            <div class="eyebrow" data-i18n="journalEyebrow">03 / OBSERVABILITY</div>
            <h2 id="journal-heading" data-i18n="journalHeading">Наблюдение и аудит</h2>
            <p class="section-subtitle" data-i18n="journalSubtitle">Сводка состояния, безопасные события и evidence export без секретов.</p>
          </div>
          <div class="journal-actions">
            <button id="export-json" class="button" type="button" data-i18n="exportJson">Экспорт JSON</button>
            <button id="export-csv" class="button button-primary" type="button" data-i18n="exportCsv">Экспорт CSV</button>
          </div>
        </div>

        <div class="journal-toolbar panel">
          <div class="journal-retention">
            <span class="eyebrow" data-i18n="retentionLabel">RETENTION</span>
            <strong id="journal-retention">—</strong>
            <small data-i18n="retentionDescription">bounded mock evidence window</small>
          </div>
          <label class="journal-search" for="journal-search">
            <span class="eyebrow" data-i18n="journalSearchLabel">ПОИСК СОБЫТИЙ</span>
            <input id="journal-search" type="search" autocomplete="off" data-i18n-placeholder="journalSearchPlaceholder" placeholder="Action, target or reason">
          </label>
          <label class="journal-filter" for="journal-result-filter">
            <span class="eyebrow" data-i18n="resultFilterLabel">РЕЗУЛЬТАТ</span>
            <select id="journal-result-filter">
              <option value="ALL" data-i18n="resultAll">Все</option>
              <option value="OK" data-i18n="resultOk">OK</option>
              <option value="OPEN" data-i18n="resultOpen">OPEN</option>
              <option value="ERROR" data-i18n="resultError">ERROR</option>
            </select>
          </label>
        </div>

        <section class="panel journal-alert-panel" aria-labelledby="journal-alert-heading">
          <div class="panel-heading">
            <div>
              <div class="eyebrow" data-i18n="alertEyebrow">HEALTH SIGNALS</div>
              <h3 id="journal-alert-heading" data-i18n="alertHeading">Сигналы для оператора</h3>
            </div>
            <span id="alert-count" class="panel-count">—</span>
          </div>
          <div id="journal-alerts" class="alert-list"></div>
        </section>

        <div class="journal-grid">
          <section class="panel history-panel" aria-labelledby="history-heading">
            <div class="panel-heading">
              <div>
                <div class="eyebrow" data-i18n="historyEyebrow">STATUS HISTORY</div>
                <h3 id="history-heading" data-i18n="historyHeading">История снимков</h3>
              </div>
              <span id="history-count" class="panel-count">—</span>
            </div>
            <div id="journal-history" class="history-list"></div>
          </section>

          <section class="panel audit-panel" aria-labelledby="events-heading">
            <div class="panel-heading">
              <div>
                <div class="eyebrow" data-i18n="eventsEyebrow">AUDIT EVENTS</div>
                <h3 id="events-heading" data-i18n="eventsHeading">Безопасный журнал</h3>
              </div>
              <span id="event-count" class="panel-count">—</span>
            </div>
            <div id="journal-events" class="audit-list"></div>
          </section>
        </div>
      </section>

      <footer class="app-footer">
        <span data-i18n="footerText">AWG CITA / PRODUCT SPRINT 4</span>
        <span class="mono" data-i18n="footerMode">MOCK LIFECYCLE · FRONTEND STATE ONLY</span>
      </footer>
    </main>
  </div>
  <div id="toast-region" class="toast-region" aria-live="polite" aria-atomic="true"></div>
  <script defer src="/static/sector-console.js"></script>
</body>
</html>"""
