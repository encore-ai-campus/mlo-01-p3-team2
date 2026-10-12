/* Floor changes share one blocking screen; the content slot can later host an ad. */
(() => {
  'use strict';
  const DURATION_MS=3000;
  window.CampusFloorTransition={
    DURATION_MS,
    create({onStart=()=>{},onFinish=()=>{},isCancelled=()=>window.CampusSession?.ending}={}){
      const dialog=document.getElementById('floorTransitionDialog');
      let blocking=false;
      dialog.addEventListener('cancel',event=>event.preventDefault());
      async function run(commit){
        if(blocking||isCancelled())return false;
        blocking=true;
        try{
          onStart();
          dialog.showModal();
          dialog.focus({preventScroll:true});
          await new Promise(resolve=>setTimeout(resolve,DURATION_MS));
          if(isCancelled())return false;
          const result=commit();
          // Paint the destination before revealing it, so the old floor cannot flash.
          await new Promise(resolve=>requestAnimationFrame(resolve));
          return result;
        }finally{
          if(dialog.open)dialog.close();
          blocking=false;
          onFinish();
          window.dispatchEvent(new Event('campus:floor-transition-end'));
        }
      }
      return {run,get blocking(){return blocking;},durationMs:DURATION_MS};
    },
  };
})();
