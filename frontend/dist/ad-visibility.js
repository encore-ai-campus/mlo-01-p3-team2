/* 광고의 투영 면적과 연속 노출 시간을 계산한다. 좌우 영역의 시간은 합산하지 않는다. */
(function(root){
  'use strict';
  function area(points){
    return Math.abs(points.reduce((sum,p,i)=>{const q=points[(i+1)%points.length];return sum+p.x*q.y-q.x*p.y;},0))/2;
  }
  function visibleRatio(points,rect){
    const total=area(points);if(!total)return 0;
    let clipped=points;
    for(const [axis,bound,sign] of [['x',rect.left,1],['x',rect.right,-1],['y',rect.top,1],['y',rect.bottom,-1]]){
      const input=clipped;clipped=[];
      for(let i=0;i<input.length;i++){
        const a=input[i],b=input[(i+1)%input.length],insideA=sign*(a[axis]-bound)>=0,insideB=sign*(b[axis]-bound)>=0;
        if(insideA)clipped.push(a);
        if(insideA!==insideB){const t=(bound-a[axis])/(b[axis]-a[axis]);clipped.push({x:a.x+t*(b.x-a.x),y:a.y+t*(b.y-a.y)});}
      }
    }
    return area(clipped)/total;
  }
  class ContinuousExposure{
    constructor(){this.starts=new Map();this.seen=new Set();}
    observe(region,key,ratio,now,active=true){
      const old=this.starts.get(region);
      if(!active||!key||ratio<0.5){this.starts.delete(region);return false;}
      if(this.seen.has(key))return false;
      if(!old||old.key!==key){this.starts.set(region,{key,at:now});return false;}
      if(now-old.at<1000)return false;
      this.seen.add(key);return true;
    }
    // 한 위치의 회차 종료가 다른 위치의 연속 노출 시간을 지우지 않도록 한다.
    reset(region){if(region===undefined)this.starts.clear();else this.starts.delete(region);}
  }
  const api={visibleRatio,ContinuousExposure};root.CampusAdVisibility=api;
  if(typeof module!=='undefined')module.exports=api;
})(globalThis);
