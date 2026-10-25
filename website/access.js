(() => {
  const api = 'https://www.agpstudios.org/api';

  window.EverenfellAccess = {
    maintenance: true,
    canPlay(user) {
      return !!user && (!this.maintenance || (typeof user.role === 'string' && user.role.toLowerCase() === 'admin'));
    },
    async session() {
      const response = await fetch(`${api}/auth/session`, { credentials: 'include' });
      if (!response.ok) throw new Error(`Account service unavailable (${response.status})`);
      const result = await response.json();
      return result.authenticated ? result.user : null;
    },
  };
})();
