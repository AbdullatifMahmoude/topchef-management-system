(function () {
  const instances = new WeakMap();
  let openInstance = null;
  let portal = null;

  function observeProgrammaticChanges() {
    ["value", "selectedIndex"].forEach((property) => {
      const descriptor = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, property);
      if (!descriptor?.set || descriptor.set.__rmsWrapped) return;
      const originalSet = descriptor.set;
      const wrappedSet = function (value) {
        originalSet.call(this, value);
        queueMicrotask(() => instances.get(this)?.sync());
      };
      wrappedSet.__rmsWrapped = true;
      Object.defineProperty(HTMLSelectElement.prototype, property, { ...descriptor, set: wrappedSet });
    });
  }

  function injectStyles() {
    if (document.getElementById("rms-custom-select-styles")) return;
    const style = document.createElement("style");
    style.id = "rms-custom-select-styles";
    style.textContent = `
      .rms_select_native{position:absolute!important;width:1px!important;height:1px!important;margin:0!important;padding:0!important;opacity:0!important;pointer-events:none!important}
      .rms_select{position:relative;box-sizing:border-box;width:100%;min-width:0;font-family:"Cairo",sans-serif;direction:rtl}
      .rms_select .rms_select_btn{display:flex!important;box-sizing:border-box!important;width:100%!important;height:44px!important;min-height:44px!important;margin:0!important;align-items:center!important;justify-content:space-between!important;gap:12px!important;padding:0 13px!important;border:1px solid rgba(241,199,91,.25)!important;border-radius:10px!important;background:rgba(12,10,7,.72)!important;color:#f5ead2!important;font:12px "Cairo",sans-serif!important;text-align:right!important;cursor:pointer!important;box-shadow:none!important;transform:none!important;transition:border-color .18s,background .18s,box-shadow .18s!important}
      .rms_select .rms_select_btn:hover{border-color:rgba(241,199,91,.48)!important;background:rgba(241,199,91,.045)!important;opacity:1!important;transform:none!important}
      .rms_select.is_open .rms_select_btn,.rms_select_btn:focus-visible{outline:0;border-color:rgba(241,199,91,.78);box-shadow:0 0 0 3px rgba(241,199,91,.09)}
      .rms_select_btn>span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
      .rms_select_arrow{flex:0 0 auto;width:7px;height:7px;border-right:1.5px solid #d9b94f;border-bottom:1.5px solid #d9b94f;transform:rotate(45deg) translateY(-2px);transition:transform .18s}
      .rms_select.is_open .rms_select_arrow{transform:rotate(225deg) translate(-1px,-1px)}
      .rms_select_portal{position:fixed;z-index:200000;box-sizing:border-box;display:none;max-height:min(280px,45vh);padding:6px;overflow:auto;overscroll-behavior:contain;border:1px solid rgba(241,199,91,.28);border-radius:11px;background:rgba(16,13,9,.985);box-shadow:0 18px 55px rgba(0,0,0,.65),0 0 0 1px rgba(255,255,255,.025) inset;direction:rtl;scrollbar-width:thin;scrollbar-color:rgba(241,199,91,.34) transparent}
      .rms_select_portal.is_visible{display:block;animation:rmsSelectIn .13s ease-out}
      .rms_select_option{display:flex;width:100%;align-items:center;justify-content:space-between;gap:10px;padding:10px 11px;border:0;border-radius:8px;background:transparent;color:rgba(255,244,220,.72);font:12px "Cairo",sans-serif;text-align:right;cursor:pointer}
      .rms_select_option:hover,.rms_select_option.is_focused{background:rgba(241,199,91,.09);color:#fff1cf}.rms_select_option.is_selected{background:rgba(241,199,91,.14);color:#f0cc65;font-weight:800}.rms_select_option.is_selected:after{content:"✓";color:#daba51}.rms_select_option:disabled{opacity:.32;cursor:not-allowed}
      @keyframes rmsSelectIn{from{opacity:0;transform:translateY(-4px)}to{opacity:1;transform:translateY(0)}}
    `;
    document.head.appendChild(style);
  }

  function getPortal() {
    if (portal) return portal;
    portal = document.createElement("div");
    portal.className = "rms_select_portal";
    document.body.appendChild(portal);
    return portal;
  }

  function enhance(select) {
    if (instances.has(select) || select.multiple || select.dataset.nativeSelect === "true") return;
    const root = document.createElement("div"); root.className = "rms_select";
    const button = document.createElement("button"); button.type = "button"; button.className = "rms_select_btn";
    button.innerHTML = '<span></span><i class="rms_select_arrow"></i>';
    select.parentNode.insertBefore(root, select); root.appendChild(select); root.appendChild(button); select.classList.add("rms_select_native");
    const instance = { select, root, button, focusedIndex: -1, sync() { const option=select.options[select.selectedIndex]; button.querySelector("span").textContent=option?.textContent||"اختر"; button.disabled=select.disabled; } };
    instances.set(select, instance); instance.sync();
    new MutationObserver(() => instance.sync()).observe(select, { childList:true, subtree:true, attributes:true });
    select.addEventListener("change", () => instance.sync());
    button.addEventListener("click", () => openInstance === instance ? closeMenu() : openMenu(instance));
    button.addEventListener("keydown", (event) => { if (["Enter"," ","ArrowDown","ArrowUp"].includes(event.key)) { event.preventDefault(); if(openInstance!==instance) openMenu(instance); moveFocus(event.key==="ArrowUp"?-1:1); } else if(event.key==="Escape") closeMenu(); });
  }

  function positionPortal(instance) {
    const rect=instance.button.getBoundingClientRect(), menu=getPortal(), gap=5, below=window.innerHeight-rect.bottom, menuHeight=Math.min(menu.scrollHeight,280,window.innerHeight*.45), openAbove=below<menuHeight+gap&&rect.top>below;
    menu.style.width=`${rect.width}px`; menu.style.left=`${rect.left}px`; menu.style.top=openAbove?`${Math.max(8,rect.top-menuHeight-gap)}px`:`${rect.bottom+gap}px`;
  }
  function openMenu(instance) {
    closeMenu(); openInstance=instance; instance.root.classList.add("is_open"); instance.button.setAttribute("aria-expanded","true");
    const menu=getPortal(); menu.innerHTML="";
    [...instance.select.options].forEach((option,index)=>{const item=document.createElement("button");item.type="button";item.className="rms_select_option"+(index===instance.select.selectedIndex?" is_selected":"");item.textContent=option.textContent;item.disabled=option.disabled;item.onclick=()=>{instance.select.value=option.value;instance.select.dispatchEvent(new Event("change",{bubbles:true}));closeMenu();instance.button.focus();};menu.appendChild(item);});
    menu.classList.add("is_visible"); positionPortal(instance); instance.focusedIndex=instance.select.selectedIndex; menu.children[instance.focusedIndex]?.scrollIntoView({block:"nearest"});
  }
  function moveFocus(step){if(!openInstance)return;const items=[...getPortal().children];let index=openInstance.focusedIndex;do{index=(index+step+items.length)%items.length;}while(items[index]?.disabled&&index!==openInstance.focusedIndex);items.forEach(x=>x.classList.remove("is_focused"));items[index]?.classList.add("is_focused");items[index]?.scrollIntoView({block:"nearest"});openInstance.focusedIndex=index;}
  function closeMenu(){if(!openInstance)return;openInstance.root.classList.remove("is_open");openInstance.button.setAttribute("aria-expanded","false");getPortal().classList.remove("is_visible");openInstance=null;}
  function scan(root=document){root.querySelectorAll?.("select").forEach(enhance);}
  document.addEventListener("click",event=>{if(openInstance&&!openInstance.root.contains(event.target)&&!getPortal().contains(event.target))closeMenu();});
  window.addEventListener("resize",closeMenu);
  window.addEventListener("scroll",(event)=>{
    // Scrolling the options is part of using the dropdown and must not close it.
    if (portal && (event.target === portal || portal.contains(event.target))) return;
    closeMenu();
  },true);
  document.addEventListener("DOMContentLoaded",()=>{injectStyles();observeProgrammaticChanges();scan();new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node.nodeType===1){if(node.matches?.("select"))enhance(node);scan(node);}}))).observe(document.body,{childList:true,subtree:true});});
  window.RMSCustomSelect={refresh(){scan();document.querySelectorAll("select").forEach(select=>instances.get(select)?.sync());}};
})();
