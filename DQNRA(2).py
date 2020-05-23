# pomp dp
from gym_minigrid.wrappers import *
env = gym.make('MiniGrid-Unlock-v0')

import tensorflow as tf
import PIL
import numpy as np
import matplotlib.pyplot as plt

class actorCritic:
    
    def __init__(self):
        # we need two network 
        # actor 
        # critic 
        self.time_step = 4
        self.action_size =env.action_space.n
        self.discount = 0.99
        with tf.variable_scope(name_or_scope="placeholders",reuse=tf.AUTO_REUSE):
            self.x_input = tf.placeholder(tf.float32,shape=(None,7,7,1),name="input")
            self.target  = tf.placeholder(tf.float32,shape=(None,1),name="target")
            self.actions  = tf.placeholder(tf.int32,shape=(None,self.action_size),name="action")
            
        self.act_value,self.policyparam,self.trainable_param = self.architecture("actor_critic_network")
        print(self.trainable_param)
      
    
    def weightVariable(self,name):
        with tf.variable_scope(name_or_scope=name,reuse=tf.AUTO_REUSE):
       
        	self.conv1 = tf.get_variable(name="conv1",shape=(2,2,1,16),initializer=tf.initializers.glorot_uniform)
        	
        	self.conv2 = tf.get_variable(name="conv2",shape=(2,2,16,32),initializer=tf.initializers.glorot_uniform)
        	
        	self.conv3 = tf.get_variable(name="conv3",shape=(2,2,32,64),initializer=tf.initializers.glorot_uniform)
        	

        	weight  = tf.random_normal(mean=1,stddev=0,shape=(64,self.action_size))
        	weight  *=  1/tf.sqrt(tf.reduce_sum(tf.pow(weight,2),axis=1,keepdims=True))
        	self.action_value  = tf.get_variable(name="action",initializer=weight)
        	weight  = tf.random_normal(mean=1,stddev=0,shape=(64,1))
        	weight  *=  1/tf.sqrt(tf.reduce_sum(tf.pow(weight,2),axis=1,keepdims=True))
        	self.value_network = tf.get_variable(name="value",initializer=weight)
            
    
    
    def architecture(self,name):
        self.weightVariable(name)
        with tf.variable_scope(name_or_scope=name,reuse=tf.AUTO_REUSE):
            
            # we need to perform the convolution operation along with LSTM cell
            
            self.conv  =  tf.nn.conv2d(self.x_input,self.conv1,strides=[1,1,1,1],padding="VALID")
            self.conv  =  tf.nn.relu(self.conv)
            self.conv  =  tf.keras.layers.MaxPool2D((2,2))(self.conv)
            

            self.conv  = tf.nn.conv2d(self.conv,self.conv2,strides=[1,1,1,1],padding="VALID")
            self.conv  = tf.nn.relu(self.conv)

            self.conv  = tf.nn.conv2d(self.conv,self.conv3,strides=[1,1,1,1],padding="VALID")
            self.conv  = tf.nn.relu(self.conv)
            
            self.conv_flat  = tf.keras.layers.Flatten()(self.conv)
            
            # we will reshape it according to the requirement of LSTM 
            # (batch,timestep,x)
           
            self.conv_flat = tf.stack([self.conv_flat]*4,axis=1)
                  
            
        
            # now we can pass this to our LSTM network 
            
            self.lstm  = tf.keras.layers.GRU(units=64,return_sequences=False)(self.conv_flat)
            # now we can use dense layers 
            # but since we are using actor critic we need to get value and action values 
            
            self.value = tf.matmul(self.lstm,self.value_network)
            self.act_value  =  tf.matmul(self.lstm,self.action_value)
            self.act_value  = tf.nn.softmax(self.act_value)
            
            # we have value
            trainable_param = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES,"actor_critic_network")

            return self.value,self.act_value,trainable_param
        
        
    

    def huberLoss(self,a,b):
    	error  = a -b
    	result  = tf.cond(tf.reduce_mean(tf.math.abs(error)) > 1.0,lambda:tf.math.abs(error)-0.5,lambda:error*error/2)
    	return result

    def actor_critic_loss(self):
        
        # the loss is going to be critic and actor losses 
        
        self.adv =  self.target - self.act_value

        self.adv  = (self.adv  - tf.keras.backend.mean(self.adv) )/(tf.keras.backend.std(self.adv) + 1e-8)
        self.critic_loss =  self.huberLoss(self.target,self.act_value)
        
        # now we gonna calculate the actor loss 
        
        self.actor = tf.nn.softmax_cross_entropy_with_logits(logits=self.policyparam,labels=self.actions)
        self.actor_loss = tf.reduce_mean(self.actor)*tf.stop_gradient(self.adv)

        # we gonna calculate the entropy to encourage more exploration 

        entropy =  tf.reduce_sum(tf.reduce_sum(self.policyparam* tf.log(tf.clip_by_value(self.policyparam, 1e-20, 1.0))))


        self.total_loss = 0.5*self.critic_loss + self.actor_loss - 0.0001*entropy
        self.grad  =  tf.gradients(self.total_loss,self.trainable_param)

        # clipped_grad  = []
        # for g in self.grad:
        # 	clipped_grad.append(tf.clip_by_value(g,clip_value_min =1,clip_value_max=-1))

        # we will clip by global norm 
        max_grad_norm = 0.5
        norm_grad,grad_ = tf.clip_by_global_norm(self.grad,max_grad_norm)

        self.grad  = zip(norm_grad,self.trainable_param)


        # now we can optimize 
        self.total_optimizer = tf.train.GradientDescentOptimizer(learning_rate=1e-5).apply_gradients(self.grad)
        # self.critic_optimizer= tf.train.AdamOptimizer(learning_rate=0.0001).minimize(self.critic_loss)
        
    
    
    def chooseAction(self,state):
        # here we choose the action
        action_prob = self.policyparam.eval(feed_dict={self.x_input:[state]})[0]
        return np.random.choice(self.action_size,p=action_prob)
        
 

class parser:
    def __init__(self):

# parser to parse the ltlf formula

        self.states = {"q1","q2","q3"}

        self.initialState  = "q1"
        self.finalState    = "q3"
        self.transitions()

    def transitions(self):

        self.transition = {

            ("q1","q1"):0,
            ("q1","q2"):0,
            ("q2","q2"):0,
            ("q2","q3"):1
        }


        self.state_dict = {

            (False,False):"q1",
            (True,False):"q2",
            (True,True):"q3"

        }



    def reset(self):
        self.initialState = "q1"


    def trace(self,key,door):

        key_door = (key,door)
        intrinsic_reward  = 0

        if self.state_dict.get(key_door) == None:
            self.reset()
            done =False
        else:
            state  = self.state_dict[key_door]
            
            done  =  False


            if self.transition.get((self.initialState,state)) == None:
                self.reset()
                done = True

            elif self.transition.get((self.initialState,state)) != None:

                intrinsic_reward = self.transition[(self.initialState,state)]
                self.initialState = state 



            if done:
                intrinsic_reward = -1

        return intrinsic_reward,done








def preprocessing(image):
    img =  PIL.Image.fromarray(image).convert("L")
    img = np.array(img).reshape(7,7,1)
    return img


tf.reset_default_graph()
RA = parser()
ac_network = actorCritic()
ac_network.actor_critic_loss()
init = tf.global_variables_initializer()

total_reward = 0
with tf.Session() as sess:
    
    sess.run(init)
    
    for episode in range(100000):
        
        # we will use monte carlo approach
        # that is we first record the data 
        # than use it 
        
        done = False
        state = env.reset()["image"]
        state  = preprocessing(state)
        
        # these are temporary data storage lists 
        save_states = []
        save_nextStates = []
        save_actions  = []
        save_rewards = []
        save_dones  = []
        c_loss = 0
        total_loss_actor_critic = 0
        in_trinsic  = 0
        count_batch = 0

        while not done:
            # plt.imshow(env.render('human'))
            # first thing we need to choose the action
            action = ac_network.chooseAction(state)
            
            # now i can perform the step in the environment 
            
            next_state,reward,done,_ = env.step(action)
            next_state = next_state["image"]

            open_door = env.door.is_open

            if env.carrying == None:
                key = False
            else:
                key = True


            intrinsic_reward,failDfa = RA.trace(key,open_door)
            in_trinsic += intrinsic_reward
            t_reward  = reward +intrinsic_reward
            
            if t_reward == 0:
            	t_reward = 0.5
            # now we gonna store the trajectory 
            
            save_states.append(state)
            save_nextStates.append(preprocessing(next_state))
            save_actions.append(action)
            save_rewards.append(t_reward)
            save_dones.append(done)

            
            total_reward += reward
            state = preprocessing(next_state)
            
            # done = failDfa


            if count_batch % 32 ==0:
            	save_states = np.array(save_states)
            	save_nextStates = np.array(save_nextStates)
            	save_actions  = np.array(save_actions)
            	save_rewards  = np.array(save_rewards)
            	save_dones    = np.array(save_dones)
            	value_predicted  = ac_network.act_value.eval(feed_dict={ac_network.x_input:save_nextStates})
            	target  = []

            	save_rewards = (save_rewards  - save_rewards.mean())/(save_rewards.std() + np.finfo(np.float32).eps)

            	for i in range(len(value_predicted)):
            		target.append(save_rewards[i] + ac_network.discount*value_predicted[i]*(1-save_dones[i]))

            	target = np.array(target)
            	action_convert = save_actions.reshape(-1)
            	onehotEncodeAction = np.eye(ac_network.action_size)[action_convert]
            	total_loss_actor_critic,_ = sess.run([ac_network.total_loss,ac_network.total_optimizer],feed_dict  = {ac_network.x_input:save_states,ac_network.target:target,ac_network.actions:onehotEncodeAction})
            	save_states = []
            	save_nextStates = []
            	save_actions = []
            	save_rewards = []
            	save_dones = []
            	count_batch = 0

            count_batch+=1

        
        if episode % 20 == 0 and episode!=0:
            
            print("After episode ",str(episode)," the total loss  ",str(np.sum(total_loss_actor_critic))," And reward ",str(total_reward))
            print("Intrinsic reward after episode ",str(episode), "  is ",str(in_trinsic))
            total_reward = 0
            
            
                
            
            
                    
            
            
    