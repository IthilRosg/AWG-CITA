(() => {
  const form = document.getElementById('login-form');
  const username = document.getElementById('username');
  const secretInput = document.getElementById('password');
  const submit = document.getElementById('login-submit');
  const error = document.getElementById('login-error');
  const toggle = document.getElementById('password-toggle');

  toggle.addEventListener('click', () => {
    const visible = secretInput.type === 'password';
    secretInput.type = visible ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(visible));
    toggle.setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
    toggle.textContent = visible ? 'Скрыть' : 'Показать';
    secretInput.focus();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    submit.querySelector('span').textContent = 'Проверяю…';
    let succeeded = false;
    try {
      const response = await fetch('/auth/login', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.value.trim(), ['password']: secretInput.value })
      });
      if (response.ok) {
        succeeded = true;
        window.location.replace('/');
        return;
      }
      secretInput.value = '';
      error.textContent = response.status === 429 ? 'Слишком много попыток. Подождите и попробуйте снова.' :
        'Не удалось войти. Проверьте логин и пароль.';
    } catch (_error) {
      error.textContent = 'Нет связи с панелью. Попробуйте ещё раз.';
    } finally {
      if (!succeeded) {
        error.hidden = false;
        submit.disabled = false;
        submit.querySelector('span').textContent = 'Войти';
      }
    }
  });
})();
