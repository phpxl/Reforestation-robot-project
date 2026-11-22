import pygame, random, math, json, socket
from pathlib import Path

pygame.init()
pygame.display.set_caption("Reforestation Robot - Ecological Simulation")
W, H = 1470, 900
screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
clock = pygame.time.Clock()

SAND=(194,166,115); SAND_DARK=(155,129,86); PANEL=(224,201,160); INK=(35,32,26); WHITE=(248,247,241)
GREEN=(100,174,91); BLUE=(63,145,220); RED=(193,67,54); ORANGE=(230,132,42)
BLACK=(27,27,27); GREY=(133,132,125); YELLOW=(244,205,65); MUTED=(92,78,58)
PALE=(241,232,209); DARKBLUE=(35,87,143)
font_cache={}
def F(size,bold=False):
    # Use Pygame's built-in font to avoid Windows SysFont enumeration errors.
    # This is reliable on Windows/Anaconda even if the system font registry is unusual.
    k=(int(size),bool(bold))
    if k not in font_cache:
        font_cache[k]=pygame.font.Font(None, int(size))
    return font_cache[k]
ASSET_DIR = Path(__file__).resolve().parent / "assets"
_image_cache = {}
def asset(name, size=None):
    key=(name, size)
    if key not in _image_cache:
        path=ASSET_DIR / name
        try:
            im=pygame.image.load(str(path)).convert_alpha()
            if size:
                im=pygame.transform.smoothscale(im, (max(1,int(size[0])), max(1,int(size[1]))))
            _image_cache[key]=im
        except (pygame.error, FileNotFoundError):
            _image_cache[key]=None
    return _image_cache[key]
def blit_asset(s, name, rect, pad=0):
    r=pygame.Rect(rect)
    im=asset(name, (max(1,r.width-pad*2), max(1,r.height-pad*2)))
    if im:
        s.blit(im, im.get_rect(center=r.center))
        return True
    return False
WEATHER_ASSETS={"Sunny":"weather_sunny.png","Cloudy":"weather_cloudy.png","Rainy":"weather_rainy.png","Sandstorm":"weather_sandstorm.png","Extreme Heat":"weather_extreme_heat.png"}
TREE_ASSETS={"seedling":"tree_seedling.png","young":"tree_young.png","mature":"tree_mature.png","dead":"tree_dead.png"}
ACTION_ASSETS={"Plant":"button_plant.png","Water":None,"Remove Dead Tree":"button_remove_dead.png","Add Mulch":"button_mulch.png","Skip":None,"Auto Spray":"button_auto_spray.png"}
ANIMAL_ASSETS={"🦊":"animal_fennec_fox.png","🐈":"animal_sand_cat.png","🐭":"animal_jerboa.png"}

def txt(s,v,x,y,size=18,col=INK,bold=False,center=False):
    im=F(size,bold).render(str(v),True,col); r=im.get_rect()
    if center:r.center=(int(x),int(y))
    else:r.topleft=(int(x),int(y))
    s.blit(im,r); return r
def button(s,r,label,color,enabled=True,icon=""):
    pygame.draw.rect(s,color if enabled else GREY,r,border_radius=11)
    pygame.draw.rect(s,INK,r,2,border_radius=11)
    image_name=ACTION_ASSETS.get(label)
    if image_name:
        ir=pygame.Rect(r.x+3,r.y+2,min(r.height-4, r.width//3),r.height-4)
        if not blit_asset(s,image_name,ir,pad=1):
            txt(s,label,r.centerx,r.centery,16,WHITE,True,True)
        else:
            txt(s,label,ir.right+4,r.centery,16,WHITE,True,True)
    else:
        # Simple drawn symbols keep buttons readable without relying on emoji fonts.
        if label=="Water":
            pygame.draw.polygon(s,(80,190,245),[(r.x+20,r.y+10),(r.x+12,r.y+25),(r.x+20,r.y+33),(r.x+28,r.y+25)])
        elif label=="Skip":
            pygame.draw.polygon(s,WHITE,[(r.x+13,r.y+10),(r.x+13,r.y+32),(r.x+27,r.y+21)])
            pygame.draw.polygon(s,WHITE,[(r.x+28,r.y+10),(r.x+28,r.y+32),(r.x+42,r.y+21)])
        txt(s,label,r.centerx+8,r.centery,16,WHITE,True,True)
def clamp(v,a,b): return max(a,min(b,v))
def new_plot():
    return dict(stage=None,moisture=100.,growth=0.,cold=0,dry=0,mulch=0,animal=None,animal_days=0,damage=0)
WEATHER=[("Sunny",35),("Cloudy",30),("Rainy",20),("Sandstorm",10),("Extreme Heat",5)]
ACTIONS=["Plant","Water","Remove Dead Tree","Add Mulch","Skip","Auto Spray"]
ICONS={"Plant":"🌱","Water":"💧","Remove Dead Tree":"🪓","Add Mulch":"🕸️","Skip":"⏭️","Auto Spray":"💦"}
COLORS={"Plant":GREEN,"Water":BLUE,"Remove Dead Tree":RED,"Add Mulch":BLACK,"Skip":GREY,"Auto Spray":(0,125,165)}
ANIMALS=["🦊","🐈","🐭"]

plots={i:new_plot() for i in range(1,10)}
water=100; day=1; weather="Cloudy"; temp=20; effect=-10
tasks_today=[]; task_history=[]; env_history=[]; career_history=[]
page="start"; report_page=0; report_start=1; selected=5
message="Click the watering can to begin."; message_time=240; frame=0; day_done=False
start_rect=rules_rect=None; action_rects={}; next_rect=end_rect=None; report_controls=None
tutorial_step=0; tutorial_back_rect=tutorial_skip_rect=None
tutorial_play_step=0; tutorial_action_rects={}; tutorial_enter_rect=None; tutorial_hint_rect=None

robot_selected = []
robot_queue_mode = False
robot_last_result = "Robot server: not connected"
queue_mode_rect = send_queue_rect = clear_queue_rect = None
ROBOT_HOST = "127.0.0.1"
ROBOT_PORT = 5001

def msg(s,t=180):
    global message,message_time
    message=s; message_time=t
def pick_weather():
    global weather,temp,effect
    weather=random.choices([x[0] for x in WEATHER],[x[1] for x in WEATHER])[0]
    temp=random.randint(41,50) if weather=="Extreme Heat" else random.randint(-10,40)
    if weather=="Sunny": effect=-random.uniform(30,50)
    elif weather=="Cloudy": effect=-random.uniform(0,29)
    elif weather=="Rainy": effect=100
    else: effect=-random.uniform(45,65)
def alive_ids(): return [i for i,p in plots.items() if p["stage"] in ("seedling","young","mature")]
def dead_ids(): return [i for i,p in plots.items() if p["stage"]=="dead"]
def start_day():
    global tasks_today,selected,day_done,water
    tasks_today=[]; selected=1; day_done=False; pick_weather()
    for p in plots.values():
        if p["stage"] in ("seedling","young","mature"):
            if weather=="Rainy": p["moisture"]=100
            else:
                tf=clamp(1+max(0,temp-20)*.012-max(0,10-temp)*.006,.55,1.45)
                p["moisture"]=clamp(p["moisture"]+effect*tf,0,100)
            if weather=="Sandstorm": p["damage"]+=1
            else:p["damage"]=max(0,p["damage"]-1)
    if weather=="Rainy": water=min(100,water+20)
def has_task_today(pid):
    """True when this plot has already received its one action for the current day."""
    return any(task["plot"] == pid and task["day"] == day for task in tasks_today)

def log_task(pid,action):
    global water
    # One action per plot per day. start_day() clears tasks_today, so the same
    # plot can be operated on again on any later day.
    if has_task_today(pid):
        msg("This plot already has one task today.")
        return
    p=plots[pid]
    if action=="Plant":
        if p["stage"] is not None: msg("Planting is only available on an empty plot."); return
        plots[pid]=new_plot(); plots[pid]["stage"]="seedling"
    elif action=="Water":
        if p["stage"] not in ("seedling","young","mature"): msg("Only living trees can be watered."); return
        if water<5: msg("Not enough water: watering costs 5 units."); return
        water-=5; p["moisture"]=clamp(p["moisture"]+35,0,100)
    elif action=="Remove Dead Tree":
        if p["stage"] is None:
            msg("This plot is already empty."); return
        plots[pid]=new_plot()
    elif action=="Add Mulch":
        if p["stage"] not in ("seedling","young","mature"): msg("Mulch can only protect a living tree."); return
        p["mulch"]=3
    elif action=="Auto Spray":
        msg("Use the Auto Spray control to spray all eligible living plots."); return
    elif action=="Skip": pass
    plots[pid]["last_action"]=action if "last_action" in plots[pid] else action
    item={"day":day,"plot":pid,"action":action,"weather":weather,"temperature":temp}
    tasks_today.append(item); task_history.append(item.copy()); msg(f"Plot {pid}: {action} scheduled.")
def finish_day():
    global day_done
    if day_done:return
    for p in plots.values():
        if p["stage"] not in ("seedling","young","mature"): continue
        if temp<0 and p["mulch"]<=0:p["cold"]+=1
        elif temp>=0:p["cold"]=0
        p["dry"]=p["dry"]+1 if p["moisture"]<=0 else 0
        if p["cold"]>=2 or p["dry"]>=2:
            p.update(stage="dead",growth=0,animal=None,animal_days=0,moisture=0,mulch=0); continue
        if weather=="Sandstorm":
            p["moisture"]=clamp(p["moisture"]-5,0,100)
            if random.random()<.12:p["damage"]+=1
        p["growth"] += .5 if p["moisture"]<30 else 1 if p["moisture"]<60 else 2
        if p["stage"]=="seedling" and p["growth"]>=5:p["growth"]-=5;p["stage"]="young"
        elif p["stage"]=="young" and p["growth"]>=8:p["growth"]-=8;p["stage"]="mature"
        if p["stage"]=="mature":
            p["growth"]=math.inf
            if p["animal"] is None and random.random()<.18:
                p["animal"]=random.choice(ANIMALS);p["animal_days"]=random.randint(2,5)
            elif p["animal"]:
                p["animal_days"]-=1
                if p["animal_days"]<=0:p["animal"]=None
        else:p["animal"]=None;p["animal_days"]=0
    for p in plots.values():
        if p["mulch"]>0:p["mulch"]-=1
    living=alive_ids()
    env_history.append(dict(day=day,weather=weather,temp=temp,effect=round(effect,1),
        avg=round(sum(plots[i]["moisture"] for i in living)/len(living),1) if living else 0,
        water=water,alive=len(living),dead=len(dead_ids()),mature=sum(p["stage"]=="mature" for p in plots.values())))
    career_history.append(dict(day=day,alive=len(living),dead=len(dead_ids()),mature=sum(p["stage"]=="mature" for p in plots.values()),water=water,tasks=len(tasks_today)))
    day_done=True
def send_robot_queue(target_ids):
    """Send selected empty plot IDs to Robot Controller V8 over local TCP."""
    if not target_ids:
        return {"success": False, "message": "Select at least one empty plot for robot planting."}

    request = {
        "action": "planting_queue",
        "targets": [f"P{pid}" for pid in target_ids]
    }

    try:
        with socket.create_connection(
            (ROBOT_HOST, ROBOT_PORT), timeout=3
        ) as client:
            client.settimeout(900)
            payload = (json.dumps(request) + "\n").encode("utf-8")
            client.sendall(payload)

            response_data = b""
            while b"\n" not in response_data:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            if not response_data:
                return {"success": False, "message": "Robot server returned no response."}

            response_line = response_data.split(b"\n", 1)[0]
            return json.loads(response_line.decode("utf-8"))

    except (OSError, socket.timeout, json.JSONDecodeError) as error:
        return {
            "success": False,
            "message": f"Cannot communicate with Robot Controller V8: {error}"
        }


def reset():
    global plots,water,day,tasks_today,task_history,env_history,career_history,page,report_page,report_start
    global robot_selected, robot_queue_mode, robot_last_result
    plots={i:new_plot() for i in range(1,10)};water=100;day=1;tasks_today=[];task_history=[];env_history=[];career_history=[]
    robot_selected=[]; robot_queue_mode=False; robot_last_result="Robot server: not connected"
    page="start";report_page=0;report_start=1
    pick_weather()
    msg("Click START SIMULATION, then choose an empty plot and Plant.",240)

def weather_fx(s,kind,rect):
    global frame
    old=s.get_clip();s.set_clip(rect)
    if kind=="Sunny":
        x,y=rect.right-70,rect.top+60;pygame.draw.circle(s,(255,220,92),(x,y),22)
        for a in range(0,360,45):
            rr=math.radians(a);pygame.draw.line(s,(255,220,92),(x+math.cos(rr)*29,y+math.sin(rr)*29),(x+math.cos(rr)*40,y+math.sin(rr)*40),3)
    elif kind=="Rainy":
        # Long, bright blue rain streaks move quickly across the whole background.
        for i in range(75):
            x=rect.x+(i*83+frame*(7+i%4))%max(1,rect.width)
            y=rect.y+(i*47+frame*(12+i%5))%max(1,rect.height)
            length=18+(i%4)*5
            pygame.draw.line(s,(35,123,207),(x,y),(x-7,y+length),3)
            pygame.draw.line(s,(115,190,245),(x-1,y+2),(x-6,y+length-2),1)
    elif kind=="Sandstorm":
        # Stronger amber haze and dense, fast diagonal grains for a clearly visible storm.
        veil=pygame.Surface((rect.width,rect.height),pygame.SRCALPHA);veil.fill((205,133,42,62));s.blit(veil,rect.topleft)
        for i in range(125):
            speed=5+(i%7)*2
            x=rect.x+(i*53+frame*speed)%max(1,rect.width)
            y=rect.y+(i*37+frame*(2+i%5))%max(1,rect.height)
            length=8+(i%5)*4
            pygame.draw.line(s,(171,105,36),(x,y),(x+length,y-2+(i%3)),2+(i%2))
            pygame.draw.circle(s,(224,169,79),(x,y),1+i%3)
    elif kind=="Extreme Heat":
        for i in range(7):
            x=rect.x+30+i*max(1,rect.width-60)//7;y=rect.y+100+int(math.sin(frame/7+i)*5)
            pygame.draw.arc(s,(232,119,54),(x,y,25,34),.2,2.8,2)
    s.set_clip(old)
def layout():
    w,h=screen.get_size();margin=24;leftw=int(w*.20);rightw=int(w*.255);gap=20;cell=min((w-leftw-rightw-2*gap-2*margin)//3,(h-280)//3);cell=max(95,cell)
    gx=margin+leftw+gap;gy=155
    return w,h,margin,leftw,rightw,gap,cell,gx,gy,gx+3*cell+gap
def plot_rect(pid,L):
    w,h,m,lw,rw,gap,cell,gx,gy,rx=L;r,c=divmod(pid-1,3)
    return pygame.Rect(gx+c*cell,gy+r*cell,cell-7,cell-7)
def draw_plot(s,pid,r,sel=False):
    p=plots[pid];stage=p["stage"]
    # Draw a clean soil tile first, then the relevant tree-state PNG.
    if p["mulch"]>0 and stage in ("seedling","young","mature"):
        blit_asset(s,"soil_mulched.png",r,2)
    elif stage is None:
        blit_asset(s,"soil_empty.png",r,2)
    elif stage=="dead":
        blit_asset(s,"tree_dead.png",r,2)
    else:
        # Soft sand-coloured plot card with a transparent tree sticker.
        pygame.draw.rect(s,(211,174,113),r,border_radius=8)
        pygame.draw.rect(s,(155,119,75),r,2,border_radius=8)
        im=asset(TREE_ASSETS[stage],(int(r.width*.78),int(r.height*.68)))
        if im:s.blit(im,im.get_rect(center=(r.centerx,r.centery-3)))
    pygame.draw.rect(s,INK,r,2,border_radius=8)
    if sel:pygame.draw.rect(s,YELLOW,r.inflate(6,6),4,border_radius=8)
    txt(s,f"Plot {pid}",r.x+7,r.y+5,15,INK,True)
    if stage is None:
        txt(s,"EMPTY",r.centerx,r.bottom-22,13,INK,True,True)
    elif stage=="dead":
        txt(s,"PLEASE REMOVE",r.centerx,r.bottom-20,12,INK,True,True)
    else:
        txt(s,f"{p['moisture']:.0f}% moisture",r.x+7,r.bottom-38,12,INK,True)
        growth="∞" if stage=="mature" else f"{p['growth']:.1f}/"+("5" if stage=="seedling" else "8")
        txt(s,f"Growth {growth}",r.x+7,r.bottom-21,12,INK,True)
        if p["animal"]:
            name=ANIMAL_ASSETS.get(p["animal"])
            if name:
                ar=pygame.Rect(r.right-48,r.y+22,43,43);blit_asset(s,name,ar,1)
        if p["mulch"]>0:
            txt(s,f"Mulch {p['mulch']}d",r.right-65,r.bottom-20,11,WHITE,True)
        if p["damage"]>0:txt(s,"!",r.right-16,r.y+20,20,RED,True,True)
def tank(s,x,y):
    txt(s,"WATER TANK",x+60,y-14,15,INK,True,True)
    r=pygame.Rect(x,y,120,145);pygame.draw.rect(s,(231,238,238),r,border_radius=13);pygame.draw.rect(s,INK,r,3,border_radius=13)
    fh=int(131*water/100)
    if fh:pygame.draw.rect(s,BLUE,(x+7,y+138-fh,106,fh),border_radius=8)
    txt(s,f"{water}/100",x+60,y+166,20,INK,True,True)
    txt(s,"Water -5",x+60,y+188,12,MUTED,False,True);txt(s,"Rain +20",x+60,y+205,12,MUTED,False,True)
def draw_start(s):
    s.fill(SAND);weather_fx(s,"Sunny",s.get_rect());w,h=s.get_size()
    txt(s,"REFORESTATION ROBOT",w//2,h*.19,43,INK,True,True);txt(s,"DESERT ECOLOGICAL RESTORATION SIMULATION",w//2,h*.25,20,MUTED,True,True)
    pygame.draw.ellipse(s,SAND_DARK,(w//2-190,h*.38,380,170))
    blit_asset(s,"tree_seedling.png",pygame.Rect(w//2-78,int(h*.385),156,160),2)
    txt(s,"Start your desert restoration journey",w//2,h*.62,21,INK,True,True)
    r=pygame.Rect(w//2-155,int(h*.72),310,72);button(s,r,"START SIMULATION",GREEN,True,"")
    return r
def draw_rules(s):
    """Three short beginner tutorial pages shown before the game starts."""
    global rules_rect, tutorial_back_rect, tutorial_skip_rect
    s.fill(SAND)
    w,h=s.get_size()
    titles=["1. WEATHER & ENVIRONMENT", "2. PLANTING & PLOT ACTIONS", "3. TREE GROWTH & SURVIVAL"]
    subtitles=[
        "Every new day brings new environmental conditions.",
        "Select a plot first. You can choose one action per plot each day, then act on it again on later days.",
        "Watch moisture, temperature and tree condition to keep trees alive."
    ]
    txt(s,"BEGINNER TUTORIAL",w//2,38,32,INK,True,True)
    txt(s,titles[tutorial_step],w//2,88,25,INK,True,True)
    txt(s,subtitles[tutorial_step],w//2,124,17,MUTED,False,True)

    card_w=min(1050,w-80); card_x=(w-card_w)//2
    card=pygame.Rect(card_x,160,card_w,min(500,h-265))
    pygame.draw.rect(s,PALE,card,border_radius=16)
    pygame.draw.rect(s,INK,card,2,border_radius=16)
    x=card.x+30; y=card.y+28; line_gap=39
    if tutorial_step==0:
        entries=[
            ("SUNNY", "Soil dries quickly: moisture loss is usually high."),
            ("CLOUDY", "Soil dries more slowly than on sunny days."),
            ("RAINY", "Living plots are replenished; the water tank gains 20 units."),
            ("SANDSTORM", "Strong moisture loss; trees may also take damage."),
            ("EXTREME HEAT", "Temperature is 41-50 C and moisture loss is high."),
            ("TEMPERATURE", "Below 0 C for two days in a row can kill an unprotected tree."),
            ("WATER TANK", "Starts at 100 units. Water costs 5; Auto Spray costs 2 per plot.")
        ]
        for label,desc in entries:
            txt(s,label,x,y,16,DARKBLUE,True); txt(s,desc,x+185,y,16,INK); y+=line_gap
    elif tutorial_step==1:
        entries=[
            ("PLANT", "Plant a seedling on an empty plot."),
            ("WATER", "Water a living tree. Each Water action costs 5 units."),
            ("AUTO SPRAY", "Water eligible living plots that have no task today; 2 units each."),
            ("ADD MULCH", "Protect a living tree from cold for 3 days."),
            ("REMOVE TREE", "Remove a tree from a plot. Dead trees must be removed before replanting."),
            ("SKIP", "Leave a plot without an action."),
            ("DAILY LIMIT", "Each plot can receive one task per day. On later days, you can act on the same plot again.")
        ]
        for label,desc in entries:
            txt(s,label,x,y,16,DARKBLUE,True); txt(s,desc,x+185,y,16,INK); y+=line_gap
    else:
        entries=[
            ("MOISTURE < 30%", "Growth increases by 0.5 points per day."),
            ("MOISTURE 30-59%", "Growth increases by 1 point per day."),
            ("MOISTURE 60-100%", "Growth increases by 2 points per day."),
            ("GROWTH STAGES", "Seedling needs 5 points to become young; young needs 8 more to mature."),
            ("DROUGHT", "Moisture at 0% for two consecutive days can kill a tree."),
            ("COLD", "Below 0 C for two consecutive days can kill a tree; active mulch protects from cold."),
            ("END OF DAY", "Use NEXT DAY to update conditions, growth, tree survival and animal visits."),
            ("CAREER REPORT", "Choose END CAREER to review results and export the JSON report.")
        ]
        for label,desc in entries:
            txt(s,label,x,y,16,DARKBLUE,True); txt(s,desc,x+185,y,16,INK); y+=35

    tutorial_back_rect=pygame.Rect(35,h-75,150,48)
    tutorial_skip_rect=pygame.Rect(w//2-100,h-75,200,48)
    rules_rect=pygame.Rect(w-205,h-75,170,48)
    button(s,tutorial_back_rect,"BACK",GREY,tutorial_step>0,"")
    button(s,tutorial_skip_rect,"SKIP TUTORIAL",BLACK,True,"")
    button(s,rules_rect,"START GAME" if tutorial_step==2 else "NEXT",GREEN,True,"")
    txt(s,f"Tutorial {tutorial_step+1}/3",w//2,h-105,14,MUTED,True,True)
    return rules_rect
def begin_playable_tutorial():
    """Start a tiny guided practice round; its state is discarded before the real game."""
    global plots, water, day, weather, temp, effect, tasks_today, task_history
    global env_history, career_history, selected, tutorial_play_step, page
    plots={i:new_plot() for i in range(1,10)}
    water=50; day=1; weather="Sunny"; temp=32; effect=-40
    tasks_today=[]; task_history=[]; env_history=[]; career_history=[]
    selected=5; tutorial_play_step=0; page="tutorial_game"
    msg("Practice mode: follow the highlighted instruction. This practice will not affect your real game.",300)

def draw_playable_tutorial(s):
    global tutorial_action_rects, tutorial_enter_rect
    s.fill(SAND); w,h,m,lw,rw,gap,cell,gx,gy,rx=layout()
    weather_fx(s,weather,s.get_rect())
    txt(s,"PRACTICE MODE — TRY IT YOURSELF",w//2,30,27,INK,True,True)
    prompts=[
        "STEP 1/4 — Select an empty plot, then click PLANT.",
        "STEP 2/4 — Select the planted plot, then click WATER (+35 moisture; costs 5 water).",
        "STEP 3/4 — Add MULCH to protect the living tree from cold for 3 days.",
        "STEP 4/4 — Select the tree and click REMOVE TREE. Then enter the real game."
    ]
    card=pygame.Rect(m,65,w-2*m,48);pygame.draw.rect(s,PALE,card,border_radius=10);pygame.draw.rect(s,INK,card,2,border_radius=10)
    txt(s,prompts[min(tutorial_play_step,3)],card.centerx,card.centery,17,INK,True,True)
    left=pygame.Rect(m,130,lw,h-220);pygame.draw.rect(s,PANEL,left,border_radius=12);pygame.draw.rect(s,INK,left,2,border_radius=12)
    x=left.x+14;y=left.y+15
    txt(s,"TODAY'S CONDITIONS",x,y,16,MUTED,True);y+=30
    blit_asset(s,WEATHER_ASSETS[weather],pygame.Rect(x,y,42,42),1)
    txt(s,"Sunny",x+48,y+4,18,INK,True);y+=50
    for line in [f"Temperature: {temp} C",f"Moisture change: {effect:.0f}%",f"Water tank: {water}/100","Sunny weather dries soil quickly.","Rain replenishes living plots.","Below 0 C for 2 days can kill an unprotected tree."]:
        txt(s,line,x,y,14,INK,line.startswith("Temperature") or line.startswith("Water"));y+=27
    txt(s,"Practice task history",x,y+8,14,INK,True);y+=32
    for item in task_history[-4:]:
        txt(s,f"Plot {item['plot']}: {item['action']}",x,y,12,MUTED);y+=19
    txt(s,"PRACTICE PLOTS",gx+1.5*cell,gy-20,18,INK,True,True)
    L=(w,h,m,lw,rw,gap,cell,gx,gy,rx)
    for i in range(1,10): draw_plot(s,i,plot_rect(i,L),selected==i)
    txt(s,"TRY THE CONTROLS",rx,130,20,INK,True)
    txt(s,f"Selected: Plot {selected}",rx,162,15,INK,True)
    p=plots[selected]; state="Empty" if p['stage'] is None else "Dead" if p['stage']=="dead" else p['stage'].title()
    txt(s,f"Plot state: {state}",rx,184,14,MUTED)
    tutorial_action_rects={}; yy=215; bw=max(190,rw-8)
    required={0:"Plant",1:"Water",2:"Add Mulch",3:"Remove Dead Tree"}[min(tutorial_play_step,3)]
    labels={"Plant":"Plant","Water":"Water","Add Mulch":"Add Mulch","Remove Dead Tree":"Remove Tree"}
    for action in ["Plant","Water","Add Mulch","Remove Dead Tree","Skip"]:
        r=pygame.Rect(rx,yy,bw,43);tutorial_action_rects[action]=r
        valid=(action==required)
        # Keep other controls visible but disabled so the learner sees the available options.
        enabled=valid and ((action=="Plant" and p['stage'] is None) or (action in ("Water","Add Mulch") and p['stage'] in ("seedling","young","mature")) or (action=="Remove Dead Tree" and p['stage'] is not None))
        if action=="Skip": enabled=False
        button(s,r,labels.get(action,action),COLORS.get(action,GREY),enabled)
        yy+=49
    tutorial_enter_rect=pygame.Rect(w-235,h-68,205,45)
    done=tutorial_play_step>=4
    button(s,tutorial_enter_rect,"ENTER REAL GAME",GREEN,done)
    txt(s,"The practice plot resets when you enter the real game.",w//2,h-18,12,MUTED,False,True)
    return tutorial_action_rects,tutorial_enter_rect

def draw_game(s):
    global action_rects, queue_mode_rect, send_queue_rect, clear_queue_rect
    s.fill(SAND);w,h,m,lw,rw,gap,cell,gx,gy,rx=layout();weather_fx(s,weather,s.get_rect())
    txt(s,"REFORESTATION ECOLOGICAL SIMULATION",w//2,35,28,INK,True,True);txt(s,"Select a plot, schedule one action, then continue or finish the day",w//2,72,15,MUTED,True,True)
    left=pygame.Rect(m,120,lw,h-220);pygame.draw.rect(s,PANEL,left,border_radius=12);pygame.draw.rect(s,INK,left,2,border_radius=12)
    x=left.x+16;y=left.y+16
    for val,size,col,bold in [("TODAY",17,MUTED,True),(f"Day {day}",28,INK,True)]:
        txt(s,val,x,y,size,col,bold);y+=31
    blit_asset(s,WEATHER_ASSETS[weather],pygame.Rect(x,y,43,43),1)
    txt(s,weather,x+48,y+4,17,INK,True);y+=48
    for val,size,col,bold in [(f"Temperature: {temp}°C",16,INK,True),(f"Moisture effect: {'Rain +100%' if weather=='Rainy' else f'{effect:.1f}%'}",13,MUTED,True),(f"Tasks: {len(tasks_today)}/9",15,INK,True),(f"Water: {water}/100",16,DARKBLUE,True),("TODAY'S TASKS",14,INK,True)]:
        txt(s,val,x,y,size,col,bold);y+=31 if size>16 else 25
    for t in tasks_today[-6:]:
        txt(s,f"{t['plot']}. {ICONS[t['action']]} {t['action']}",x,y,11,INK);y+=17

    # Robot queue controls are kept in the lower part of the left sidebar.
    txt(s, f"Robot queue: {len(robot_selected)} plot(s) selected", left.x+14, left.bottom-153, 13, DARKBLUE, True)
    queue_mode_rect = pygame.Rect(left.x+12, left.bottom-128, left.width-24, 34)
    half_w = (left.width-30)//2
    send_queue_rect = pygame.Rect(left.x+12, left.bottom-85, half_w, 36)
    clear_queue_rect = pygame.Rect(left.x+18+half_w, left.bottom-85, half_w, 36)
    button(s, queue_mode_rect, "QUEUE MODE: ON" if robot_queue_mode else "QUEUE MODE: OFF",
           DARKBLUE if robot_queue_mode else GREY, True)
    button(s, send_queue_rect, "SEND QUEUE", GREEN, bool(robot_selected))
    button(s, clear_queue_rect, "CLEAR", ORANGE, bool(robot_selected))
    txt(s, robot_last_result[:38], left.x+14, left.bottom-38, 11, MUTED)

    txt(s,"RESTORATION PLOTS",gx+1.5*cell,gy-25,20,INK,True,True)
    for i in range(1,10):
        is_highlighted = (selected == i and not robot_queue_mode) or (i in robot_selected)
        draw_plot(s,i,plot_rect(i,(w,h,m,lw,rw,gap,cell,gx,gy,rx)),is_highlighted)
    txt(s,"PLOT CONTROL",rx,125,22,INK,True);txt(s,f"Selected: Plot {selected}",rx,160,15,INK,True)
    p=plots[selected];state="Empty" if p["stage"] is None else "Dead — remove" if p["stage"]=="dead" else p["stage"].title()
    txt(s,state,rx,182,13,MUTED,True)
    bw=max(190,rw-8);yy=210;action_rects={}
    enabled={"Plant":p["stage"] is None,"Water":p["stage"] in ("seedling","young","mature") and water>=5,
             "Remove Dead Tree":p["stage"] is not None,"Add Mulch":p["stage"] in ("seedling","young","mature"),
             "Skip":True,"Auto Spray":bool(alive_ids()) and water>=2}
    labels={"Plant":"Plant","Water":"Water","Remove Dead Tree":"Remove Tree",
            "Add Mulch":"Add Mulch","Skip":"Skip","Auto Spray":"Auto Spray"}
    for a in ACTIONS:
        r=pygame.Rect(rx,yy,bw,43);action_rects[a]=r;button(s,r,labels[a],COLORS[a],enabled[a],ICONS[a]);yy+=49
    tank(s,rx+max(0,(rw-120)//2),min(yy+18,h-245))
    next_rect=pygame.Rect(w-320,h-75,145,48);end_rect=pygame.Rect(w-163,h-75,145,48)
    button(s,next_rect,"NEXT DAY",BLUE,True,"➡️");button(s,end_rect,"END CAREER",RED,True,"🏁")
    txt(s,"Weather updates daily. Growth, tree survival, animal visits and mulch duration resolve at day end.",w//2,h-20,12,MUTED,False,True)
    return next_rect,end_rect
def report_draw(s):
    global report_controls
    s.fill(SAND);w,h=s.get_size()
    titles=["PLANTING / ROBOT TASK HISTORY","FINAL PLOT STATUS","ENVIRONMENTAL HISTORY","CAREER SUMMARY","ROBOT EXPORT PREVIEW"]
    txt(s,titles[report_page],w//2,40,28,INK,True,True);txt(s,f"Report page {report_page+1}/5",w//2,78,15,MUTED,True,True)
    if report_page==0:
        days=list(range(report_start,min(day,report_start+5)+1));x0=45;y0=130;cw=min(175,(w-90)//(len(days)+1));rh=min(58,(h-250)//9)
        heads=["Plot"]+[f"Day {d}" for d in days]
        for c,head in enumerate(heads):
            r=pygame.Rect(x0+c*cw,y0,cw,36);pygame.draw.rect(s,(224,224,224),r);pygame.draw.rect(s,INK,r,1);txt(s,head,r.centerx,r.centery,12,INK,True,True)
        for pid in range(1,10):
            r=pygame.Rect(x0,y0+36+(pid-1)*rh,cw,rh);pygame.draw.rect(s,(224,224,224),r);pygame.draw.rect(s,INK,r,1);txt(s,f"Plot {pid}",r.centerx,r.centery,11,INK,True,True)
            for j,d in enumerate(days):
                c=pygame.Rect(x0+(j+1)*cw,y0+36+(pid-1)*rh,cw,rh)
                item=next((t for t in task_history if t["day"]==d and t["plot"]==pid),None);a=item["action"] if item else "-"
                pygame.draw.rect(s,COLORS.get(a,SAND),c);pygame.draw.rect(s,INK,c,1);txt(s,a.upper() if a!="-" else "-",c.centerx,c.centery,9,WHITE if a!="-" else INK,True,True)
    elif report_page==1:
        _,_,m,lw,rw,gap,cell,gx,gy,rx=layout()
        for i in range(1,10):
            r,c=divmod(i-1,3);rr=pygame.Rect(55+c*min(300,(w-150)//3),135+r*190,min(280,(w-150)//3)-10,175);draw_plot(s,i,rr)
    elif report_page==2:
        headers=["Day","Weather","Temp","Effect","Avg moisture","Water","Alive","Dead","Mature"]
        vals=[(e["day"],e["weather"],f'{e["temp"]}°C',f'{e["effect"]}%',f'{e["avg"]}%',e["water"],e["alive"],e["dead"],e["mature"]) for e in env_history]
        widths=[70,125,75,100,115,80,65,65,75];scale=min(1,(w-70)/sum(widths));widths=[int(a*scale) for a in widths];x=(w-sum(widths))//2;y=125;rh=min(42,(h-190)//max(2,len(vals)+1))
        for row,data in enumerate([headers]+[list(v) for v in vals]):
            x=(w-sum(widths))//2
            for j,val in enumerate(data):
                r=pygame.Rect(x,y+row*rh,widths[j],rh);pygame.draw.rect(s,(224,224,224) if row==0 else WHITE,r);pygame.draw.rect(s,INK,r,1);txt(s,val,r.centerx,r.centery,10,INK,True,True);x+=widths[j]
                if y+(row+1)*rh>h-100:break
    elif report_page==3:
        stats=[("Days simulated",day),("Actions recorded",len(task_history)),("Living trees",len(alive_ids())),("Dead trees awaiting removal",len(dead_ids())),("Mature trees",sum(p["stage"]=="mature" for p in plots.values())),("Water remaining",f"{water}/100 units"),("Current animal sightings",sum(bool(p["animal"]) for p in plots.values())),("Plots with active mulch",sum(p["mulch"]>0 for p in plots.values()))]
        y=130
        for label,val in stats:
            r=pygame.Rect(w//2-260,y,520,50);pygame.draw.rect(s,PALE,r,border_radius=8);pygame.draw.rect(s,INK,r,1,border_radius=8);txt(s,label,r.x+15,r.centery,15,INK,True);im=F(16,True).render(str(val),True,GREEN);s.blit(im,(r.right-15-im.get_width(),r.centery-im.get_height()//2));y+=60
    else:
        data={"career_days":day,"water_remaining":water,"plots":{str(i):{"stage":plots[i]["stage"],"moisture":round(plots[i]["moisture"],1),"growth":"infinity" if math.isinf(plots[i]["growth"]) else round(plots[i]["growth"],1),"mulch_days":plots[i]["mulch"],"animal":plots[i]["animal"]} for i in plots},"tasks":task_history,"environment":env_history}
        for j,line in enumerate(json.dumps(data,indent=2,ensure_ascii=False).splitlines()[:27]):txt(s,line[:120],60,120+j*21,12,INK)
    prev=pygame.Rect(35,h-65,150,45);restart=pygame.Rect(w//2-100,h-65,200,45);nxt=pygame.Rect(w-185,h-65,150,45)
    button(s,prev,"PREVIOUS",GREY,report_page>0,"⬅️");button(s,restart,"RESTART",GREEN,True,"🔄");button(s,nxt,"NEXT",BLUE,report_page<4,"➡️")
    prevd=nextd=None
    if report_page==0:
        prevd=pygame.Rect(205,h-65,145,45);nextd=pygame.Rect(365,h-65,145,45)
        button(s,prevd,"PREV DAYS",GREY,report_start>1,"⬅️");button(s,nextd,"NEXT DAYS",BLUE,report_start+6<=day,"➡️")
    save=pygame.Rect(w//2-90,h-120,180,40);button(s,save,"SAVE JSON",BLACK,True,"💾")
    report_controls=(prev,restart,nxt,prevd,nextd,save)
def export():
    data={"career_days":day,"water_remaining":water,"plots":{str(i):{"stage":plots[i]["stage"],"moisture":round(plots[i]["moisture"],1),"growth":"infinity" if math.isinf(plots[i]["growth"]) else round(plots[i]["growth"],1),"mulch_days":plots[i]["mulch"],"animal":plots[i]["animal"]} for i in plots},"tasks":task_history,"environment":env_history}
    Path.cwd().joinpath("reforestation_robot_export.json").write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    msg("Saved reforestation_robot_export.json",240)

reset()
# All nine plots begin empty; the player chooses when and where to plant.
plots={i:new_plot() for i in range(1,10)}
tasks_today=[]; task_history=[]; env_history=[]; career_history=[]
running=True
while running:
    frame+=1
    if message_time>0:message_time-=1
    if page=="start":start_rect=draw_start(screen)
    elif page=="rules":rules_rect=draw_rules(screen)
    elif page=="tutorial_game":tutorial_action_rects,tutorial_enter_rect=draw_playable_tutorial(screen)
    elif page=="game":next_rect,end_rect=draw_game(screen)
    elif page=="report":report_draw(screen)
    if message_time>0:
        w,h=screen.get_size();r=pygame.Rect(w//2-330,h-48,660,32);pygame.draw.rect(screen,WHITE,r,border_radius=8);pygame.draw.rect(screen,INK,r,1,border_radius=8);txt(screen,message,r.centerx,r.centery,14,INK,True,True)
    pygame.display.flip()
    for e in pygame.event.get():
        if e.type==pygame.QUIT:running=False
        elif e.type==pygame.VIDEORESIZE:screen=pygame.display.set_mode(e.size,pygame.RESIZABLE)
        elif e.type==pygame.KEYDOWN and e.key==pygame.K_ESCAPE:
            if page=="game":finish_day();page="report";report_page=3
            elif page=="report":page="game"
            elif page=="tutorial_game":reset();page="game";msg("Practice exited. The real game is ready.")
            else:running=False
        elif e.type==pygame.MOUSEBUTTONDOWN and e.button==1:
            pos=e.pos
            if page=="start" and start_rect and start_rect.collidepoint(pos):
                begin_playable_tutorial()
            elif page=="rules":
                if tutorial_skip_rect and tutorial_skip_rect.collidepoint(pos):
                    reset();page="game";msg("Tutorial skipped. Select a plot and choose an action.")
                elif tutorial_back_rect and tutorial_back_rect.collidepoint(pos) and tutorial_step>0:
                    tutorial_step-=1
                elif rules_rect and rules_rect.collidepoint(pos):
                    if tutorial_step<2:
                        tutorial_step+=1
                    else:
                        reset();page="game";msg("Tutorial complete. Select an empty plot and choose Plant.")
            elif page=="tutorial_game":
                action=next((a for a,r in tutorial_action_rects.items() if r.collidepoint(pos)),None)
                if action:
                    required={0:"Plant",1:"Water",2:"Add Mulch",3:"Remove Dead Tree"}.get(tutorial_play_step)
                    if tutorial_play_step>=4:
                        msg("Practice complete. Click ENTER REAL GAME.")
                    elif action!=required:
                        msg(f"For this step, try {required}.")
                    elif has_task_today(selected):
                        msg("This plot already has a task in this practice step.")
                    else:
                        before=len(task_history)
                        log_task(selected,action)
                        if len(task_history)>before:
                            tutorial_play_step+=1
                            tasks_today=[]  # Each practice step is a fresh mini-day.
                            if tutorial_play_step==1:
                                water=50; plots[selected]["moisture"]=35
                                msg("Great! A seedling is planted. Now water the same plot.")
                            elif tutorial_play_step==2:
                                msg("Good watering! Add mulch to protect the tree from cold.")
                            elif tutorial_play_step==3:
                                msg("Mulch applied. Now remove the tree to learn plot removal.")
                            else:
                                msg("Practice complete! Enter the real game when ready.",300)
                elif tutorial_enter_rect and tutorial_enter_rect.collidepoint(pos):
                    if tutorial_play_step>=4:
                        reset();page="game";msg("Practice complete. Your real career starts with nine empty plots.",240)
                    else:
                        msg("Finish the four guided actions first, or press ESC to leave.")
                else:
                    L=layout()
                    for i in range(1,10):
                        if plot_rect(i,L).collidepoint(pos):
                            selected=i
                            msg(f"Plot {i} selected. Follow the highlighted practice step.")
                            break
            elif page=="game":
                # Robot queue controls are handled before ordinary game actions.
                if queue_mode_rect and queue_mode_rect.collidepoint(pos):
                    robot_queue_mode = not robot_queue_mode
                    msg("Planting queue ON: select empty plots for robot planting." if robot_queue_mode
                        else "Queue mode OFF: normal plot controls restored.")
                elif send_queue_rect and send_queue_rect.collidepoint(pos):
                    if not robot_selected:
                        msg("Select at least one empty plot for robot planting.")
                    else:
                        result = send_robot_queue(robot_selected)
                        robot_last_result = result.get("message", "No response")
                        if result.get("success") is True:
                            expected_targets = [f"P{pid}" for pid in robot_selected]
                            confirmed_targets = result.get("targets", [])
                            if set(confirmed_targets) == set(expected_targets):
                                planted_count = 0
                                for pid in list(robot_selected):
                                    if plots[pid]["stage"] is None and not any(
                                        task["plot"] == pid for task in tasks_today
                                    ):
                                        log_task(pid, "Plant")
                                        planted_count += 1
                                robot_selected.clear()
                                robot_last_result = f"{planted_count} plot(s) planted in game"
                                msg(
                                    f"Robot completed {planted_count} planting task(s).",
                                    300
                                )
                            else:
                                robot_last_result = "Controller target confirmation mismatch"
                                msg("Controller response did not match the selected plots; no plots were planted.", 300)
                            print("Robot V8 response:", json.dumps(result, indent=2, ensure_ascii=False))
                        else:
                            msg(f"Robot communication failed: {robot_last_result}", 240)
                            print("Robot V8 error:", robot_last_result)
                elif clear_queue_rect and clear_queue_rect.collidepoint(pos):
                    robot_selected.clear()
                    msg("Robot task queue cleared.")
                elif robot_queue_mode:
                    L=layout()
                    clicked_plot=None
                    for i in range(1,10):
                        if plot_rect(i,L).collidepoint(pos):
                            clicked_plot=i
                            break
                    if clicked_plot is not None:
                        if clicked_plot in robot_selected:
                            robot_selected.remove(clicked_plot)
                            msg(f"Plot {clicked_plot} removed from robot queue.")
                        elif plots[clicked_plot]["stage"] is not None:
                            msg("Robot planting queue only accepts empty plots.")
                        elif has_task_today(clicked_plot):
                            msg("This plot already has a task today.")
                        else:
                            robot_selected.append(clicked_plot)
                            robot_selected.sort()
                            msg(f"Plot {clicked_plot} added to robot queue.")
                    elif next_rect and next_rect.collidepoint(pos):
                        finish_day();day+=1;start_day()
                    elif end_rect and end_rect.collidepoint(pos):
                        finish_day();page="report";report_page=0;report_start=max(1,day-5)
                else:
                    # Handle action/navigation buttons before plot selection.
                    action=next((a for a,r in action_rects.items() if r.collidepoint(pos)),None)
                    if action:
                        if action=="Auto Spray":
                            # A manual spray can be used in any weather. It costs 2 water
                            # units per eligible living plot and respects the one-task-per-day rule.
                            targets=[pid for pid in alive_ids()
                                     if not has_task_today(pid)]
                            done=0
                            for pid in targets:
                                if water<2:
                                    break
                                water-=2
                                plots[pid]["moisture"]=clamp(plots[pid]["moisture"]+25,0,100)
                                item={"day":day,"plot":pid,"action":"Auto Spray","weather":weather,"temperature":temp}
                                tasks_today.append(item);task_history.append(item.copy());done+=1
                            if done:
                                msg(f"Auto spray treated {done} living plot(s); 2 water units each.")
                            elif not alive_ids():
                                msg("Plant a tree first; Auto Spray needs at least one living tree.")
                            elif not targets:
                                msg("All living plots already have a task today.")
                            else:
                                msg("Not enough water to spray a living plot.")
                        elif any(t["plot"]==selected for t in tasks_today):
                            msg("This plot already has one task today.")
                        else:
                            log_task(selected,action)
                    elif next_rect and next_rect.collidepoint(pos):
                        finish_day();day+=1;start_day()
                    elif end_rect and end_rect.collidepoint(pos):
                        finish_day();page="report";report_page=0;report_start=max(1,day-5)
                    else:
                        L=layout()
                        for i in range(1,10):
                            if plot_rect(i,L).collidepoint(pos):
                                selected=i
                                msg(f"Plot {i} selected.")
                                break
            elif page=="report" and report_controls:
                prev,restart,nxt,prevd,nextd,save=report_controls
                if prev.collidepoint(pos) and report_page>0:report_page-=1
                elif nxt.collidepoint(pos) and report_page<4:report_page+=1
                elif restart.collidepoint(pos):
                    reset(); tutorial_step=0
                elif save.collidepoint(pos):export()
                elif prevd and prevd.collidepoint(pos) and report_start>1:report_start=max(1,report_start-6)
                elif nextd and nextd.collidepoint(pos) and report_start+6<=day:report_start+=6
    clock.tick(60)
pygame.quit()
