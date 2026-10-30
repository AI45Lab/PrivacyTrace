(() => {
  'use strict';
  const config = window.PRIVACYTRACE_CONFIG || {};
  if (config.repository) {
    document.querySelectorAll('[data-repo]').forEach(link => { link.href = config.repository; });
    document.querySelectorAll('[data-doc]').forEach(link => {
      link.href = `${config.repository}/blob/main/${link.dataset.doc}`;
    });
  }
  if (config.dataset) {
    document.getElementById('dataset-link').href = config.dataset;
    document.querySelectorAll('[data-dataset]').forEach(link => { link.href = config.dataset; });
  }
  if (config.paper) {
    const holder = document.getElementById('paper-status');
    const link = document.createElement('a');
    link.href = config.paper;
    link.className = 'external-link button is-normal is-rounded is-dark';
    link.append(...holder.querySelector('.button').childNodes);
    holder.replaceChildren(link);
  }
})();
