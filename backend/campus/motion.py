"""Server-owned movement, collision, classroom interactions and navigation."""
from functools import lru_cache
import heapq
import json
from uuid import uuid4
import math
from pathlib import Path
import time
from .doors import DOORS, footprint as door_footprint

KEYS = frozenset({'w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'})
LOOK_DIRECTIONS = {(0, -1): 'up', (0, 1): 'down', (-1, 0): 'left', (1, 0): 'right',
                   (-1, -1): 'up-left', (1, -1): 'up-right',
                   (-1, 1): 'down-left', (1, 1): 'down-right'}
SPEED = 125 * 1.25
CLASSROOM_TRANSITION_DELAY = 2.0

class ControlError(ValueError):
    pass

@lru_cache(maxsize=1)
def geometry():
    return json.loads((Path(__file__).parent / 'data/worlds.json').read_text(encoding='utf-8'))

def inside(rectangle, x, y):
    return rectangle['x'] <= x <= rectangle['x'] + rectangle['w'] and rectangle['y'] <= y <= rectangle['y'] + rectangle['h']

def rect_distance(rectangle, x, y):
    return math.hypot(max(rectangle['x']-x, 0, x-rectangle['x']-rectangle['w']),
                      max(rectangle['y']-y, 0, y-rectangle['y']-rectangle['h']))

class World:
    def __init__(self, data):
        self.data = data
        self.objects = {row['id']: row for row in data['objects']}
        self.buckets = {}
        for collider in data['colliders']:
            margin = collider['pad'] + data['radius'] + 1
            for y in range(math.floor((collider['y']-margin)/64), math.floor((collider['y']+collider['h']+margin)/64)+1):
                for x in range(math.floor((collider['x']-margin)/64), math.floor((collider['x']+collider['w']+margin)/64)+1):
                    self.buckets.setdefault((x,y), []).append(collider)

    def walkable(self, x, y, doors=None):
        if not math.isfinite(x) or not math.isfinite(y):
            return False
        if self.data['privateRoom']:
            if not (23 <= x <= 617 and 23 <= y <= 493):
                return False
            radius = self.data['radius']
            return not any(row['x']-radius < x < row['x']+row['w']+radius and row['y']-radius < y < row['y']+row['h']+radius
                           for row in self.buckets.get((math.floor(x/64),math.floor(y/64)), ()))
        entrance = self.data.get('entrance')
        if not any(inside(row,x,y) for row in self.data['rooms']) and not (entrance and inside(entrance,x,y)):
            return False
        radius = self.data['radius']
        if any(rect_distance(row,x,y) < radius+row['pad'] for row in self.buckets.get((math.floor(x/64),math.floor(y/64)), ())):
            return False
        if self.data['id'] == 'campus':
            for door_id, data in DOORS.items():
                if rect_distance(door_footprint(data, bool((doors or {}).get(door_id))), x, y) < radius:
                    return False
        return True

    def closest(self, x, y, doors=None, maximum=80):
        if self.walkable(x,y,doors):
            return {'x':x,'y':y}
        for radius in range(4, maximum+1, 4):
            for i in range(24):
                angle=i*math.pi/12
                xx,yy=x+math.cos(angle)*radius,y+math.sin(angle)*radius
                if self.walkable(xx,yy,doors):
                    return {'x':xx,'y':yy}
        return None

    def move(self, pose, dx, dy, doors=None):
        before = pose['x'],pose['y']
        count = max(1, math.ceil(math.hypot(dx,dy)/3))
        for _ in range(count):
            if self.walkable(pose['x']+dx/count,pose['y'],doors):
                pose['x']+=dx/count
            if self.walkable(pose['x'],pose['y']+dy/count,doors):
                pose['y']+=dy/count
        pose['moving']=math.hypot(pose['x']-before[0],pose['y']-before[1])>.01
        return pose['moving']

    def distance(self, obj, pose, doors=None):
        if obj.get('door') and obj['id'] in DOORS:
            return rect_distance(door_footprint(DOORS[obj['id']], bool((doors or {}).get(obj['id']))), pose['x'],pose['y'])
        if obj.get('interactionPoint'):
            return math.hypot(pose['x']-obj['interactionPoint'][0],pose['y']-obj['interactionPoint'][1])
        rect=obj.get('footprint',{})
        return rect_distance(rect,pose['x'],pose['y']) if all(key in rect for key in ('x','y','w','h')) else math.inf

    def clear(self, start, end, doors=None):
        count=math.ceil(math.hypot(end['x']-start['x'],end['y']-start['y'])/2)
        return all(self.walkable(start['x']+(end['x']-start['x'])*(i/count if count else 0),
                                 start['y']+(end['y']-start['y'])*(i/count if count else 0),doors) for i in range(count+1))

    def route(self, start, end, doors=None, step=6):
        if not self.walkable(start['x'],start['y'],doors) or not self.walkable(end['x'],end['y'],doors):
            return None
        if self.clear(start,end,doors):
            return [end]
        columns,rows=math.ceil(self.data['width']/step),math.ceil(self.data['height']/step)
        def point(cell):
            return {'x':cell[0]*step,'y':cell[1]*step}
        def nearest(pose):
            gx,gy=round(pose['x']/step),round(pose['y']/step)
            best=None;distance=math.inf
            for ring in range(13):
                for yy in range(gy-ring,gy+ring+1):
                    for xx in range(gx-ring,gx+ring+1):
                        if not 0<=xx<columns or not 0<=yy<rows or max(abs(xx-gx),abs(yy-gy))!=ring:
                            continue
                        candidate=point((xx,yy));delta=math.hypot(candidate['x']-pose['x'],candidate['y']-pose['y'])
                        if delta<distance and self.walkable(candidate['x'],candidate['y'],doors) and self.clear(pose,candidate,doors):
                            best,distance=(xx,yy),delta
                if best is not None and ring*step>distance+step:
                    break
            return best
        first,last=nearest(start),nearest(end)
        if first is None or last is None:
            return None
        heap=[(0,first)];scores={first:0};parents={};closed=set()
        while heap:
            _,cell=heapq.heappop(heap)
            if cell in closed:
                continue
            if cell==last:
                raw=[end];current=last
                while current!=first:
                    raw.append(point(current));current=parents[current]
                raw.append(point(first));raw.reverse()
                smooth=[];anchor=start;i=0
                while i<len(raw):
                    j=i
                    while j+1<len(raw) and self.clear(anchor,raw[j+1],doors):
                        j+=1
                    smooth.append(raw[j]);anchor=raw[j];i=j+1
                return smooth
            closed.add(cell)
            for dx,dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                next_cell=(cell[0]+dx,cell[1]+dy)
                if not 0<=next_cell[0]<columns or not 0<=next_cell[1]<rows or next_cell in closed:
                    continue
                candidate=point(next_cell)
                if dx and dy and (not self.walkable(cell[0]*step,candidate['y'],doors) or not self.walkable(candidate['x'],cell[1]*step,doors)):
                    continue
                if not self.walkable(candidate['x'],candidate['y'],doors) or not self.clear(point(cell),candidate,doors):
                    continue
                cost=scores[cell]+(math.sqrt(2) if dx and dy else 1)
                if cost<scores.get(next_cell,math.inf):
                    scores[next_cell]=cost;parents[next_cell]=cell
                    heuristic=math.hypot(next_cell[0]-last[0],next_cell[1]-last[1])
                    heapq.heappush(heap,(cost+heuristic,next_cell))
        return None

@lru_cache(maxsize=4)
def world(name):
    data=geometry()['worlds'].get(name) or geometry()['classrooms'].get(name)
    if data is None:
        raise ControlError('이동할 공간을 확인해 주세요.')
    return World(data)

class MotionController:
    def __init__(self, position, doors=None):
        self.pose={**position,'moving':False}
        self.poke_direction=position['dir']
        self.poke_diagonal_at=-math.inf
        self.keys=set();self.last_input=-math.inf;self.last_portal=time.monotonic()
        self.ignored_portal=None;self.pending_transfer=None;self.interior=None;self.route=[]
        self.last_classroom_transition=-math.inf;self.classroom_exit_armed=False
        self.world=world(position['floor'])
        entrance=self.world.data.get('entrance')
        outside=entrance and inside(entrance,position['x'],position['y'])
        target=(None if outside else self.world.closest(position['x'],position['y'],doors)) or self.world.closest(*self.world.data['spawn'],doors)
        if target is None:
            raise ControlError('시작 위치를 확인해 주세요.')
        self.pose.update(target)
        self.exit_return={**target}
        self.ignore_current_portal()

    def ignore_current_portal(self):
        self.ignored_portal=next((row['objectId'] for row in self.world.data['portals'] if inside(row,self.pose['x'],self.pose['y'])),None)

    def input(self, keys, now=None):
        if not isinstance(keys,list) or len(keys)>8 or any(not isinstance(key,str) or key not in KEYS for key in keys):
            raise ControlError('이동 입력을 확인해 주세요.')
        self.keys=set(keys);self.last_input=time.monotonic() if now is None else now
        if self.interior and 'arrowdown' not in self.keys:
            self.classroom_exit_armed=True
        dx=int('d' in self.keys or 'arrowright' in self.keys)-int('a' in self.keys or 'arrowleft' in self.keys)
        dy=int('s' in self.keys or 'arrowdown' in self.keys)-int('w' in self.keys or 'arrowup' in self.keys)
        if dx or dy:
            direction=LOOK_DIRECTIONS[(dx,dy)]
            previous=self.interior.get('poke_direction',self.interior['actor']['dir']) if self.interior else self.poke_direction
            diagonal_at=self.interior.get('poke_diagonal_at',-math.inf) if self.interior else self.poke_diagonal_at
            # Releasing a diagonal's two keys often spans two frames. Keep its facing for that short gap.
            if dx and dy:
                if self.interior:self.interior['poke_diagonal_at']=self.last_input
                else:self.poke_diagonal_at=self.last_input
            elif '-' in previous and self.last_input-diagonal_at<.08:
                direction=previous
            if self.interior:
                self.interior['poke_direction']=direction
            else:
                self.poke_direction=direction
        if self.keys:
            self.route=[]

    def private_near(self):
        if not self.interior:
            return None
        data=world(self.interior['subject']).data;actor=self.interior['actor'];exit=data['exit']
        if math.hypot(actor['x']-exit['interactionPoint'][0],actor['y']-exit['interactionPoint'][1])<35:
            return exit
        kind=('multiple_choice' if 70<=actor['x']<=270 else 'fill_blank' if 390<=actor['x']<=590 else None) if 145<=actor['y']<=413 else None
        if not kind:
            return None
        rows=[obj for obj in data['objects'] if obj.get('action')=='learning' and obj.get('contentType')==kind]
        return min(rows,key=lambda obj:math.hypot(actor['x']-obj['interactionPoint'][0],actor['y']-obj['interactionPoint'][1]),default=None)

    def hints(self, doors=None):
        rows=[obj for obj in self.world.data['objects'] if obj.get('name') and self.world.distance(obj,self.pose,doors)<35]
        nearby=min(rows,key=lambda obj:self.world.distance(obj,self.pose,doors),default=None)
        room=next((row for row in reversed(self.world.data['rooms']) if inside(row,self.pose['x'],self.pose['y'])),None)
        entrance=self.world.data.get('entrance')
        exiting=bool(entrance and inside(entrance,self.pose['x'],self.pose['y']) and self.pose['y']>entrance['y']+6)
        return {'nearbyId':nearby['id'] if nearby else None,'roomId':room['id'] if room else None,'exitRequired':exiting}

    def snapshot(self, doors=None):
        interior=None
        if self.interior:
            near=self.private_near()
            interior={'subject':self.interior['subject'],'actor':dict(self.interior['actor']),
                      'nearby':{key:near[key] for key in ('id','name','contentType') if key in near} if near else None,
                      'exitCooldownMs':math.ceil(max(0,CLASSROOM_TRANSITION_DELAY-(time.monotonic()-self.last_classroom_transition))*1000)}
        return {'main':dict(self.pose),'hints':self.hints(doors),'interior':interior}

    def tick(self, seconds, doors=None, now=None):
        now=time.monotonic() if now is None else now
        seconds=max(0,min(seconds,.04));events=[]
        keys=self.keys if now-self.last_input<=.35 else set()
        actor=self.interior['actor'] if self.interior else self.pose
        active_world=world(self.interior['subject']) if self.interior else self.world
        was_moving=actor['moving'];actor['moving']=False
        previous=dict(self.pose)
        if (self.interior and self.classroom_exit_armed and now-self.last_classroom_transition>=CLASSROOM_TRANSITION_DELAY
                and 'arrowdown' in keys and (near:=self.private_near()) and near['id']=='classroom-exit'):
            self.leave_classroom(doors,now=now);keys=set();actor=self.pose;active_world=self.world
        if not self.pending_transfer:
            dx=int('d' in keys or 'arrowright' in keys)-int('a' in keys or 'arrowleft' in keys)
            dy=int('s' in keys or 'arrowdown' in keys)-int('w' in keys or 'arrowup' in keys)
            if dx or dy:
                horizontal='right' if dx>0 else 'left';vertical='down' if dy>0 else 'up'
                if not dx: actor['dir']=vertical
                elif not dy or not was_moving or actor['dir'] not in {horizontal,vertical}: actor['dir']=horizontal
                length=math.hypot(dx,dy);angle=active_world.data['angle'];tilt=active_world.data['tilt']
                vx=math.cos(angle)*dx/length+math.sin(angle)*dy/length/tilt
                vy=-math.sin(angle)*dx/length+math.cos(angle)*dy/length/tilt
                active_world.move(actor,vx*SPEED*seconds,vy*SPEED*seconds,doors)
            elif self.route and not self.interior:
                target=self.route[0];dx=target['x']-actor['x'];dy=target['y']-actor['y'];length=math.hypot(dx,dy)
                if length<3:
                    self.route.pop(0)
                else:
                    distance=min(length,SPEED*seconds)
                    active_world.move(actor,dx/length*distance,dy/length*distance,doors)
        if not self.interior:
            if self.pose['floor']=='campus' and now-self.last_classroom_transition>=CLASSROOM_TRANSITION_DELAY:
                for gate in geometry()['gates']:
                    # Open classroom thresholds do not depend on a door state.
                    if previous['y']>=gate['y'] or self.pose['y']<gate['y']:
                        continue
                    ratio=(gate['y']-previous['y'])/(self.pose['y']-previous['y'])
                    x=previous['x']+(self.pose['x']-previous['x'])*ratio
                    if gate['left']<x<gate['right'] and inside(gate['room'],self.pose['x'],self.pose['y']):
                        spawn=world(gate['subject']).data['spawn']
                        self.interior={'subject':gate['subject'],'gate':gate,'actor':{'x':spawn[0],'y':spawn[1],'dir':'up','moving':False}}
                        self.pose['moving']=False;self.keys=set();self.route=[]
                        self.last_classroom_transition=now;self.classroom_exit_armed=False;break
            entrance=self.world.data.get('entrance')
            if entrance and self.pose['y']<=entrance['y']-12 and any(inside(row,self.pose['x'],self.pose['y']) for row in self.world.data['rooms']):
                self.exit_return={'x':self.pose['x'],'y':self.pose['y']}
            if self.ignored_portal:
                portal=next((row for row in self.world.data['portals'] if row['objectId']==self.ignored_portal),None)
                if portal is None or not inside(portal,self.pose['x'],self.pose['y']):
                    self.ignored_portal=None
            if not self.interior and not self.pending_transfer and not self.ignored_portal and now-self.last_portal>=1.2:
                portal=next((row for row in self.world.data['portals'] if inside(row,self.pose['x'],self.pose['y'])),None)
                if portal:
                    events.append(self.offer_transfer(portal['objectId'],doors))
        return events

    def offer_transfer(self, object_id, doors=None):
        if not isinstance(object_id,str):
            raise ControlError('계단이나 포탈을 확인해 주세요.')
        obj=self.world.objects.get(object_id)
        if not obj or not obj.get('toFloor') or self.world.distance(obj,self.pose,doors)>=35 or self.interior:
            raise ControlError('계단이나 포탈 가까이에서 이용해 주세요.')
        self.pending_transfer=obj;self.ad_transfer_id=None;self.keys=set();self.route=[];self.pose['moving']=False
        return {'type':'transfer_offer','objectId':obj['id'],'floor':obj['toFloor'],'confirm':obj.get('confirmTransfer',False)}

    def leave_classroom(self, doors=None, *, now=None):
        if not self.interior:
            raise ControlError('학습교실에서 이용해 주세요.')
        now=time.monotonic() if now is None else now
        if now-self.last_classroom_transition<CLASSROOM_TRANSITION_DELAY:
            raise ControlError('입장 후 2초 뒤에 나갈 수 있어요.')
        gate=self.interior['gate'];target=self.world.closest((gate['left']+gate['right'])/2,gate['y']-18,doors)
        if target is None:
            raise ControlError('교실 출입구를 확인해 주세요.')
        self.pose.update(target,moving=False);self.interior=None;self.keys=set()
        self.route=[];self.last_classroom_transition=now;self.classroom_exit_armed=False
        self.poke_direction=self.pose['dir']

    def command(self, action, data, doors=None):
        if action=='prepare_transfer':
            return self.offer_transfer(data.get('objectId'),doors)
        if action=='cancel_transfer':
            if self.pending_transfer:
                self.ignored_portal=self.pending_transfer['id']
            self.pending_transfer=None;self.keys=set()
        elif action=='begin_transfer':
            obj=self.pending_transfer
            if not obj or data.get('floor')!=obj['toFloor'] or self.world.distance(obj,self.pose,doors)>=35:
                raise ControlError('이동할 계단이나 포탈을 먼저 선택해 주세요.')
            destination=world(obj['toFloor']);arrival=obj.get('arrival') or destination.data['spawn']
            if destination.closest(*arrival,doors) is None:
                raise ControlError('도착 위치를 확인해 주세요.')
            if not getattr(self,'ad_transfer_id',None):
                self.ad_transfer_id=str(uuid4())
            return {'type':'transfer_ready','transfer_id':self.ad_transfer_id}
        elif action=='transfer':
            obj=self.pending_transfer
            if not obj or data.get('floor')!=obj['toFloor'] or self.world.distance(obj,self.pose,doors)>=35:
                raise ControlError('이동할 계단이나 포탈을 먼저 선택해 주세요.')
            destination=world(obj['toFloor']);arrival=obj.get('arrival') or destination.data['spawn']
            target=destination.closest(*arrival,doors)
            if target is None:
                raise ControlError('도착 위치를 확인해 주세요.')
            self.world=destination;self.pose.update(target,floor=destination.data['id'],moving=False)
            self.poke_direction=self.pose['dir']
            self.pending_transfer=None;self.keys=set();self.route=[];self.last_portal=time.monotonic();self.ignore_current_portal()
        elif action=='cancel_exit':
            if self.interior or not self.hints(doors)['exitRequired']:
                raise ControlError('캠퍼스 출구에서 이용해 주세요.')
            target=self.world.closest(self.exit_return['x'],self.exit_return['y'],doors,30)
            if target:
                self.pose.update(target,moving=False)
            self.keys=set()
        elif action=='interact':
            if not self.interior:
                raise ControlError('학습교실에서 이용해 주세요.')
            near=self.private_near()
            if not near:
                raise ControlError('학습 영역이나 출입구 가까이에서 이용해 주세요.')
            if near['id']=='classroom-exit':
                self.leave_classroom(doors)
            else:
                self.keys=set();self.interior['actor']['moving']=False
                return {'type':'learning_open','subject':self.interior['subject'],'questionType':near['contentType']}
        elif action=='navigate':
            x,y=data.get('x'),data.get('y')
            if type(x) not in (int,float) or type(y) not in (int,float) or not 0<=x<=self.world.data['width'] or not 0<=y<=self.world.data['height'] or not math.isfinite(x) or not math.isfinite(y) or self.interior:
                raise ControlError('목적지를 확인해 주세요.')
            route=self.world.route(self.pose,{'x':x,'y':y},doors)
            if route is None:
                raise ControlError('이동 가능한 경로가 없습니다.')
            self.route=route;self.keys=set()
            return {'type':'route','points':route}
        elif action=='open_booth':
            object_id=data.get('objectId')
            obj=self.world.objects.get(object_id) if isinstance(object_id,str) else None
            if not obj or obj.get('action')!='booth' or self.interior or self.world.distance(obj,self.pose,doors)>=35:
                raise ControlError('부스 중앙의 E 표시 가까이로 이동해 주세요.')
            self.keys=set();self.route=[]
            return {'type':'booth_open','objectId':object_id}
        else:
            raise ControlError('지원하지 않는 요청입니다.')
        return {'type':'state'}
