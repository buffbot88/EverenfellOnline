(() => {
  window.EverenfellAccess = {
    canPlay(user) {
      return user?.can_play === true;
    },
    async session() {
      const response = await fetch('/api/auth/session', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error(`Account service unavailable (${response.status})`);
      const result = await response.json();
      return result.authenticated ? result.user : null;
    },
  };
})();
