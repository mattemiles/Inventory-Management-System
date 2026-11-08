// Apply the last signed-in appearance before the stylesheet is loaded.
// Only a display mode and accent color are stored; no account data is cached.
(()=>{
    'use strict';
    const key='cmt-last-appearance';
    function valid(value){return value&&['light','dark','system'].includes(value.mode)&&typeof value.accent==='string'&&/^#[a-f0-9]{6}$/i.test(value.accent)}
    function read(){try{const value=JSON.parse(localStorage.getItem(key));return valid(value)?{mode:value.mode,accent:value.accent.toLowerCase()}:null}catch{return null}}
    function write(value){if(!valid(value))return;try{localStorage.setItem(key,JSON.stringify({mode:value.mode,accent:value.accent.toLowerCase()}))}catch{}}
    function apply(value){
        if(!valid(value))return;
        const root=document.documentElement;
        root.dataset.mode=value.mode;
        root.style.setProperty('--accent-color',value.accent);
        const rgb=value.accent.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
        const luminance=.2126*rgb[0]+.7152*rgb[1]+.0722*rgb[2];
        root.style.setProperty('--accent-ink',luminance>.179?'#000000':'#ffffff');
    }
    window.CmtAppearanceCache=Object.freeze({read,write});
    apply(read());
})();
