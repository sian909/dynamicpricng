
const won = value => `${Math.round(Number(value)||0).toLocaleString("ko-KR")}원`;
const colors = {parent:"#2563eb", smart:"#dc2626", loyal:"#078353"};

async function api(url, options={}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `${response.status} 오류`);
  }
  return response.json();
}

class UserPanel {
  constructor(root) {
    this.root = root;
    this.user = JSON.parse(root.dataset.user);
    this.products = JSON.parse(root.dataset.products);
    this.current = this.products[0];
    this.prices = {};
    this.products.forEach(product => this.prices[product.id] = product.base_price + this.user.starting_bias);

    this.dwell = 0;
    this.purchaseIntent = 50;
    this.sensitivity = this.user.sensitivity;
    this.urgency = this.user.urgency;
    this.fired = new Set();
    this.pauseUntil = 0;
    this.busy = false;
    this.closed = false;

    this.renderTabs();
    this.renderProduct();
    this.bind();
    this.startTimer();
  }

  renderTabs() {
    this.root.querySelector(".product-tabs").innerHTML = this.products.map(product => `
      <button class="product-tab ${product.id === this.current.id ? "active" : ""}" data-product="${product.id}">
        <b>${product.brand}</b><span>${won(product.base_price)}</span>
      </button>
    `).join("");
  }

  renderProduct() {
    const product = this.current;
    this.root.querySelector(".brand-label").textContent = product.brand;
    this.root.querySelector(".product-name").textContent = product.name;
    this.root.querySelector(".rating").textContent =
      `★ ${product.rating} · 후기 ${product.reviews.toLocaleString()}개 · 재고 ${product.stock}개`;
    this.root.querySelector(".reference-price").textContent = `공통 기준가 ${won(product.base_price)}`;
    this.root.querySelector(".personal-price").textContent = won(this.prices[product.id]);
    this.root.querySelector(".dwell b").textContent = this.dwell;
  }

  bind() {
    this.root.addEventListener("click", async event => {
      if (this.closed) return;

      const productButton = event.target.closest("[data-product]");
      if (productButton) {
        this.pauseUntil = Date.now() + 4000;
        await this.switchProduct(productButton.dataset.product);
        return;
      }

      const actionButton = event.target.closest("[data-action]");
      if (actionButton) {
        this.pauseUntil = Date.now() + 4000;
        await this.sendAction(actionButton.dataset.action, actionButton.textContent.trim());
      }
    });
  }

  async switchProduct(productId) {
    if (this.busy || this.closed) return;

    if (productId === this.current.id) {
      await this.sendAction("same_brand", "같은 상품을 다시 확인");
      return;
    }

    const previous = this.current;
    this.current = this.products.find(product => product.id === productId);
    this.dwell = 0;
    this.fired = new Set();
    this.renderTabs();
    this.renderProduct();
    await this.sendAction("compare_brand", `${previous.brand} → ${this.current.brand} 비교`);
  }

  startTimer() {
    const milestones = {4:"dwell_4", 8:"dwell_8", 15:"dwell_15"};

    setInterval(async () => {
      if (this.closed) return;

      this.dwell += 1;
      this.root.querySelector(".dwell b").textContent = this.dwell;

      if (Date.now() < this.pauseUntil) return;

      const action = milestones[this.dwell];
      if (action && !this.fired.has(this.dwell)) {
        this.fired.add(this.dwell);
        await this.sendAction(action, `${this.dwell}초 체류`);
      }
    }, 1000);
  }

  updateSignals(action) {
    const positive = [
      "view_review","deep_review","check_shipping","check_stock",
      "favorite","add_cart","same_brand","dwell_4","dwell_8","dwell_15"
    ];

    if (positive.includes(action)) {
      this.purchaseIntent = Math.min(100, this.purchaseIntent + (action === "add_cart" ? 15 : 6));
    }

    if (["coupon","sort_low","compare_brand","remove_cart"].includes(action)) {
      this.purchaseIntent = Math.max(5, this.purchaseIntent - 7);
      this.sensitivity = Math.min(100, this.sensitivity + 5);
    }

    if (action === "check_shipping") {
      this.urgency = Math.min(100, this.urgency + 10);
    }
  }

  closePanel(finalPrice) {
    this.closed = true;
    this.root.querySelectorAll("button").forEach(button => button.disabled = true);

    const status = this.root.querySelector(".collection-status");
    status.className = "collection-status closed";
    status.textContent = "■ 구매 완료 · 수집 종료";

    this.root.querySelector(".signal-text").innerHTML =
      `<b>구매 완료</b><br>최종 가격 ${won(finalPrice)}<br>이 사용자에 대한 추가 클릭·체류 데이터는 더 이상 저장되지 않습니다.`;
  }

  async sendAction(action, label) {
    if (this.busy || this.closed) return;
    this.busy = true;

    if (action !== "purchase_complete") {
      this.updateSignals(action);
    }

    const oldPrice = this.prices[this.current.id];
    const signal = this.root.querySelector(".signal-text");
    signal.textContent = "AI가 행동 신호를 분석하는 중입니다…";

    try {
      const data = await api("/api/event", {
        method: "POST",
        headers: {"Content-Type":"application/json"},
        body: JSON.stringify({
          user_id: this.user.id,
          product_id: this.current.id,
          action,
          old_price: oldPrice,
          dwell_seconds: this.dwell,
          purchase_intent: this.purchaseIntent,
          price_sensitivity: this.sensitivity,
          urgency: this.urgency
        })
      });

      this.prices[this.current.id] = data.new_price;
      this.renderProduct();

      const badge = this.root.querySelector(".price-change");
      badge.className = `price-change ${data.delta > 0 ? "up" : data.delta < 0 ? "down" : "neutral"}`;
      badge.textContent =
        data.delta > 0 ? `▲ ${won(data.delta)}` :
        data.delta < 0 ? `▼ ${won(Math.abs(data.delta))}` :
        action === "purchase_complete" ? "구매 확정" : "변동 없음";

      signal.innerHTML =
        `<b>${label}</b><br>${data.reason}<br>${won(oldPrice)} → ${won(data.new_price)} · AI 확신도 ${data.confidence}%`;

      if (action === "purchase_complete") {
        this.closePanel(data.new_price);
      }

      await refreshDatabase();
      document.getElementById("dbStatus").textContent = "● 실시간 저장 정상";
      document.getElementById("dbStatus").style.color = "#078353";
    } catch (error) {
      signal.innerHTML = `<b style="color:#fecaca">저장 오류</b><br>${error.message}`;
      document.getElementById("dbStatus").textContent = "● 데이터베이스 연결 오류";
      document.getElementById("dbStatus").style.color = "#dc2626";
    } finally {
      this.busy = false;
    }
  }
}

async function refreshDatabase() {
  const [events, summary] = await Promise.all([
    api("/api/events?limit=150"),
    api("/api/summary")
  ]);

  document.getElementById("totalEvents").textContent = summary.total.toLocaleString();
  document.getElementById("activeUsers").textContent = summary.active_users;
  document.getElementById("completedUsers").textContent = summary.completed_users;
  document.getElementById("spread").textContent = `${summary.spread.toFixed(1)}%p`;

  document.getElementById("eventRows").innerHTML = events.length ? events.map(event => `
    <tr>
      <td>${new Date(event.created_at).toLocaleTimeString("ko-KR",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</td>
      <td>${event.user_name}</td>
      <td>${event.reason}</td>
      <td>${event.brand}</td>
      <td class="${event.delta > 0 ? "delta-up" : event.delta < 0 ? "delta-down" : ""}">
        ${event.delta > 0 ? "+" : ""}${won(event.delta)}
      </td>
      <td>${won(event.new_price)}</td>
      <td class="${event.session_closed ? "status-closed" : ""}">
        ${event.session_closed ? "구매 완료" : "수집 중"}
      </td>
    </tr>
  `).join("") : `<tr><td colspan="7">아직 저장된 행동이 없습니다.</td></tr>`;

  drawChart(events);
}

function drawChart(events) {
  const canvas = document.getElementById("priceChart");
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  canvas.width = Math.max(1, rect.width * dpr);
  canvas.height = Math.max(1, rect.height * dpr);

  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);

  const w = rect.width, h = rect.height;
  const L=44,R=18,T=28,B=30;
  ctx.clearRect(0,0,w,h);

  const chronological = events.slice().reverse().slice(-45);
  if (!chronological.length) {
    ctx.fillStyle="#98a2b3";
    ctx.font="12px sans-serif";
    ctx.fillText("행동이 저장되면 사용자별 가격 편차가 나타납니다.", L, h/2);
    return;
  }

  const ids = ["parent","smart","loyal"];
  const series = {parent:[],smart:[],loyal:[]};
  const current = {};

  chronological.forEach(event => {
    current[event.user_id] = ((event.new_price - event.reference_price) / event.reference_price) * 100;
    ids.forEach(id => series[id].push(current[id] ?? null));
  });

  const values = Object.values(series).flat().filter(v => v !== null);
  let min = Math.min(-7, ...values) - 2;
  let max = Math.max(7, ...values) + 2;

  const x = index => L + (w-L-R) * (index / Math.max(1, chronological.length-1));
  const y = value => T + (max-value)/(max-min) * (h-T-B);

  ctx.font="10px sans-serif";
  ctx.textAlign="right";
  ctx.textBaseline="middle";

  for (let i=0;i<5;i++) {
    const value = max - (max-min)*i/4;
    const yy = y(value);
    ctx.strokeStyle = Math.abs(value) < 1 ? "#94a3b8" : "#e2e8f0";
    ctx.lineWidth = Math.abs(value) < 1 ? 1.5 : 1;
    ctx.beginPath(); ctx.moveTo(L,yy); ctx.lineTo(w-R,yy); ctx.stroke();
    ctx.fillStyle="#64748b";
    ctx.fillText(`${value > 0 ? "+" : ""}${value.toFixed(0)}%`, L-6, yy);
  }

  ids.forEach(id => {
    const arr = series[id];
    ctx.strokeStyle = colors[id];
    ctx.fillStyle = colors[id];
    ctx.lineWidth = 2.7;
    ctx.beginPath();

    let started = false;
    let last = null;

    arr.forEach((value,index) => {
      if (value === null) return;
      if (!started) {
        ctx.moveTo(x(index), y(value));
        started = true;
      } else {
        ctx.lineTo(x(index), y(last));
        ctx.lineTo(x(index), y(value));
      }
      last = value;
    });

    ctx.stroke();
  });

  const names = {parent:"김민서", smart:"박지훈", loyal:"이선영"};
  let lx = L;
  ctx.textAlign="left";

  ids.forEach(id => {
    ctx.fillStyle = colors[id];
    ctx.fillRect(lx,10,12,3);
    ctx.fillStyle = "#334155";
    ctx.fillText(names[id], lx+16, 12);
    lx += 82;
  });
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".user-panel").forEach(element => new UserPanel(element));

  document.getElementById("resetDb").addEventListener("click", async () => {
    if (!confirm("저장된 모든 시연 데이터를 삭제할까요?")) return;
    await api("/api/reset", {method:"POST"});
    location.reload();
  });

  refreshDatabase().catch(console.error);
  setInterval(() => refreshDatabase().catch(console.error), 2500);
  window.addEventListener("resize", () => refreshDatabase().catch(console.error));
});
