/**
 * GEOPULSE A.I. - INTERACTIVE ENGINE
 * Simulates real-time indexing, ticks, dynamic sparklines, and responsive navigation
 */

document.addEventListener('DOMContentLoaded', () => {
  initISTTime();
  initTickerTape();
  initDynamicUpdates();
  initMobileMenu();
  initNavigationScroll();
});

/**
 * 1. LIVE Indian Standard Time (IST) Clock
 */
function initISTTime() {
  const timeEl = document.getElementById('current-ist-time');
  if (!timeEl) return;

  function updateIST() {
    // Get current time in IST (UTC+5:30)
    const now = new Date();
    const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
    const istOffset = 5.5 * 3600000;
    const istTime = new Date(utc + istOffset);

    let hours = istTime.getHours();
    let minutes = istTime.getMinutes();
    
    // Format to HH:MM
    hours = hours < 10 ? '0' + hours : hours;
    minutes = minutes < 10 ? '0' + minutes : minutes;

    timeEl.textContent = `${hours}:${minutes}`;
  }

  updateIST();
  setInterval(updateIST, 30000); // Update every 30 seconds
}

/**
 * 2. Infinite Ticker Tape Duplication for Smooth Loop
 */
function initTickerTape() {
  const track = document.querySelector('.ticker-track');
  if (!track) return;

  // Duplicate the ticker track nodes to create the seamless infinite scroll
  const clone = track.cloneNode(true);
  clone.setAttribute('aria-hidden', 'true');
  document.getElementById('ticker-wrapper').appendChild(clone);
}

/**
 * 3. Mobile Navigation Menu Toggle
 */
function initMobileMenu() {
  const menuToggle = document.getElementById('menuToggle');
  const navMenu = document.getElementById('navMenu');

  if (!menuToggle || !navMenu) return;

  menuToggle.addEventListener('click', () => {
    menuToggle.classList.toggle('active');
    navMenu.classList.toggle('active');
  });

  // Close menu when navigation item is clicked
  const navLinks = document.querySelectorAll('.nav-link');
  navLinks.forEach(link => {
    link.addEventListener('click', () => {
      menuToggle.classList.remove('active');
      navMenu.classList.remove('active');
    });
  });
}

/**
 * 4. Active Navigation Highlighting on Scroll
 */
function initNavigationScroll() {
  const sections = document.querySelectorAll('section');
  const navLinks = document.querySelectorAll('.nav-link');

  window.addEventListener('scroll', () => {
    let current = '';
    
    sections.forEach(section => {
      const sectionTop = section.offsetTop;
      const sectionHeight = section.clientHeight;
      if (pageYOffset >= (sectionTop - 150)) {
        current = section.getAttribute('id');
      }
    });

    navLinks.forEach(link => {
      link.classList.remove('active');
      if (link.getAttribute('href') === `#${current}`) {
        link.classList.add('active');
      }
    });
  });
}

/**
 * 5. Dynamic Data Simulation
 * Simulates micro-changes in prices and index readings to make the dashboard look "alive"
 */
function initDynamicUpdates() {
  // Stats elements
  const signalsEl = document.getElementById('stat-signals');
  const sourcesEl = document.getElementById('stat-sources');
  const refreshEl = document.getElementById('stat-refresh');
  const crudeScoreEl = document.getElementById('crude-score');

  // Let's randomize indices occasionally
  setInterval(() => {
    // Marquee/Ticker value updates disabled to keep them static as requested.
  }, 1000);

  function animateStats() {
    // Animate primary score gauge (crude pressure score)
    if (crudeScoreEl) {
      let currentScore = parseInt(crudeScoreEl.textContent);
      let diff = Math.floor((Math.random() - 0.5) * 2); // -1, 0, 1
      let newScore = Math.max(78, Math.min(88, currentScore + diff)); // bound it around 82
      crudeScoreEl.textContent = newScore;

      // Adjust pointer & bar style width
      const gaugeProg = document.querySelector('.gauge-progress');
      const gaugePointer = document.querySelector('.gauge-pointer');
      if (gaugeProg && gaugePointer) {
        gaugeProg.style.width = `${newScore}%`;
        gaugePointer.style.left = `${newScore}%`;
      }
    }
  }
}
