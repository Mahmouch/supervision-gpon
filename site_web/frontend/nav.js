/**
 * nav.js — Version NOC Premium Corrected
 */

document.addEventListener("DOMContentLoaded", () => {
    const user = window.getStoredUser();
    if (!user) {
        window.location.href = "login.html";
        return;
    }
    renderSidebar(user);
});

function renderSidebar(user) {
    const sidebarContainer = document.getElementById('sidebar-container');
    if (!sidebarContainer) return;

    const roleLabel = user.role === 'admin' ? 'ADMINISTRATEUR' : `TECHNICIEN — ${user.assigned_gouvernorat || 'SFAX'}`;
    const roleColor = user.role === 'admin' ? 'text-blue-400' : 'text-emerald-400';
    const dotColor = user.role === 'admin' ? 'bg-blue-500' : 'bg-emerald-500';
    const currentPage = window.location.pathname.split("/").pop() || "index.html";

    const navItems = [
        { href: 'index.html', icon: 'dashboard', label: 'Dashboard' },
        { href: 'anomalies.html', icon: 'warning', label: 'Anomalies' },
        { href: 'equipements.html', icon: 'router', label: 'Équipements' },
        { href: 'reclamations.html', icon: 'support_agent', label: 'Réclamations' }
    ];
    // Page admin uniquement visible par les administrateurs
    if (user.role === 'admin') {
        navItems.splice(2, 0, { href: 'prediction.html', icon: 'psychology', label: 'Prédiction IA' });
        navItems.push({ href: 'analytique.html', icon: 'analytics', label: 'Flux Analytique' });
        navItems.push({ href: 'admin.html', icon: 'manage_accounts', label: 'Techniciens' });
    }


    sidebarContainer.innerHTML = `
    <div class="sidebar fixed top-0 left-0 h-screen w-[280px] sidebar-glass z-[100] flex flex-col shadow-2xl border-r border-white/5">
      <div class="p-8">
        <div class="flex items-center gap-3 mb-1">
          <img src="nexmon.png" alt="NEXMON Logo" class="w-9 h-9 object-contain rounded-lg shadow-lg">
          <h5 class="text-xl font-extrabold text-white tracking-wider">NEX<span class="text-blue-500">MON</span></h5>
        </div>
        <p class="text-[9px] text-slate-500 font-bold uppercase tracking-[0.18em] ml-[48px]">Next-Gen Monitoring</p>
      </div>
      
      <div class="px-8 py-6 mb-4">
        <div class="flex items-center gap-4 bg-slate-800/40 p-4 rounded-2xl border border-white/5">
          <div class="w-1.5 h-1.5 rounded-full ${dotColor} animate-pulse shadow-[0_0_8px_rgba(59,130,246,0.5)]"></div>
          <div>
            <div class="text-xs font-bold text-slate-200">${user.username || 'User'}</div>
            <div class="text-[9px] font-black ${roleColor} mt-0.5 tracking-wider uppercase">${roleLabel}</div>
          </div>
        </div>
      </div>

      <nav class="flex-1 px-4 space-y-1.5 overflow-y-auto">
        ${navItems.map(item => `
          <a href="${item.href}" class="nav-link-tailwind ${currentPage === item.href ? 'active' : ''} flex items-center gap-4 px-6 py-3.5 rounded-xl transition-all duration-200 group">
            <span class="material-symbols-outlined text-[20px] ${currentPage === item.href ? 'text-blue-400' : 'text-slate-500 group-hover:text-slate-300'}">${item.icon}</span>
            <span class="text-sm font-bold ${currentPage === item.href ? 'text-white' : 'text-slate-400 group-hover:text-slate-200'}">${item.label}</span>
          </a>
        `).join("")}
      </nav>

      <div class="p-6 mt-auto">
        <button onclick="window.logout()" class="w-full flex items-center justify-center gap-3 py-4 rounded-2xl text-[11px] font-black text-red-500 hover:bg-red-500/10 transition-all border border-red-500/10 hover:border-red-500/20 tracking-widest uppercase">
          <span class="material-symbols-outlined text-sm">logout</span> Déconnexion
        </button>
      </div>
    </div>
    `;
}

// Global logout function
window.logout = function() {
    if (window.clearAuth) window.clearAuth();
    else {
      localStorage.removeItem('gpon_access_token');
      localStorage.removeItem('gpon_user_profile');
    }
    window.location.href = "login.html";
};

// Injected CSS for Nav
const styleNav = document.createElement('style');
styleNav.textContent = `
  .nav-link-tailwind.active {
    background: rgba(59, 130, 246, 0.12) !important;
    box-shadow: inset 0 0 12px rgba(59, 130, 246, 0.05);
    border-left: 3px solid #3b82f6;
  }
  .nav-link-tailwind {
    border-left: 3px solid transparent;
  }
  .sidebar-glass {
    background: rgba(10, 15, 26, 0.75) !important;
  }
`;
document.head.appendChild(styleNav);
