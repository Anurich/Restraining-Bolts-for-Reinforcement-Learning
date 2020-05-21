from gym_minigrid.wrappers import *
env = gym.make('MiniGrid-Unlock-v0')
import numpy as np
import tensorflow.compat.v1 as tf
tf.disable_v2_behavior()
from collections import deque
import PIL
import random
import matplotlib.pyplot as plt
import flloat
from flloat.parser.ltlf import LTLfParser
from tensorflow.compat.v1.keras.backend import set_session

config = tf.compat.v1.ConfigProto()
config.gpu_options.allow_growth = True
config.gpu_options.per_process_gpu_memory_fraction = 0.9
sess = tf.Session(config=config)
set_session(sess)


class sumtree:

    def __init__(self, capacity):
        self.total_capacity = capacity
        self.tree_capacity = 2 * self.total_capacity - 1
        self.data_pointer = 0
        self.tree = np.zeros(self.tree_capacity)
        self.data = np.zeros(self.tree_capacity, dtype=object)

    def add(self, priority, data_value):

        # this will give us the index where i have to insert the value in the datastructure
        self.idx = self.data_pointer + self.total_capacity - 1

        self.data[self.data_pointer] = data_value

        self.update(self.idx, priority)

        self.data_pointer += 1
        if self.data_pointer >= self.total_capacity:
            self.data_pointer = 0

    def propogate(self, idx, change):

        while idx != 0:
            idx = (idx - 1) // 2
            self.tree[idx] += change

    def update(self, idx, prio):

        # first thing is i need to propogate the change to upward
        # as well as i need to set the value in the tree at particular index

        self.change = prio - self.tree[idx]
        self.tree[idx] = prio

        # now i will propogate the change
        self.propogate(idx, prio)

    def retreive(self, val):
        leaf_index = 0
        parentIndex = 0

        while True:

            leftChild = 2 * parentIndex + 1
            rightChild = 2 * parentIndex + 2

            if leftChild >= len(self.tree):
                leaf_index = parentIndex
                break

            if val <= self.tree[leftChild]:
                parentIndex = leftChild

            else:
                val -= self.tree[leftChild]
                parentIndex = rightChild

        data_index = leaf_index - self.total_capacity + 1

        return leaf_index, self.tree[leaf_index], self.data[data_index]

    def total_priority(self):
        return self.tree[0]


class memory:

    # this class basically gonna have two function
    # sample the batches based on priority and store the data into  sum tree datastructure

    def __init__(self, capacity):
        self.capacity = capacity

        self.PER_e = 0.01  # Hyperparameter that we use to avoid some experiences to have 0 probability of being taken
        self.PER_b = 0.4  # importance-sampling, from initial value increasing to 1
        self.PER_b_increment_per_sampling = 0.001
        self.epsilon = 0.01
        self.minimumPriority = 1
        self.alpha = 0.6
        self.sumtree = sumtree(capacity)

    def store(self, experiance):
        # basically getting all the leaf values and find the max out of it
        max_priority = np.max(self.sumtree.tree[-self.sumtree.total_capacity:])

        if max_priority == 0:
            max_priority = self.minimumPriority

        self.sumtree.add(max_priority, experiance)

    def sample(self, n):
        # n is the number of batch
        minibatch = []

        b_idx = np.empty((n,), dtype=np.int32)
        ISWeights = np.empty((n, 1))
        # Calculate the priority segment
        # Here, as explained in the paper, we divide the Range[0, ptotal] into n ranges

        self.beta = np.min([1., self.PER_b + self.PER_b_increment_per_sampling])  # max = 1
        priority_segment = self.sumtree.total_priority() / n  # priority segment
        min_prob = np.min(self.sumtree.tree[-self.sumtree.total_capacity:]) / self.sumtree.total_priority()
        for i in range(n):
            # A value is uniformly sample from each range
            a, b = priority_segment * i, priority_segment * (i + 1)
            value = np.random.uniform(a, b)

            # Experience that correspond to each value is retrieved
            index, priority, data = self.sumtree.retreive(value)

            prob = priority / self.sumtree.total_priority()
            ISWeights[i, 0] = np.power(prob / min_prob, -self.beta)

            b_idx[i] = index
            minibatch.append([data[0], data[1], data[2], data[3], data[4]])

        return b_idx, minibatch, ISWeights

    def batch_update(self, tree_idx, abs_errors):
        abs_errors += self.epsilon  # convert to abs and avoid 0
        clipped_errors = np.minimum(abs_errors, self.minimumPriority)
        ps = np.power(clipped_errors, self.alpha)
        for ti, p in zip(tree_idx, ps):
            self.sumtree.update(ti, p)

        # now we need to look for maximum value


class DDQN:

    def __init__(self):
        self.memory_class = memory(1000)
        self.discount = 0.95
        self.batch_size = 32
        self.EPS_START = 0.9
        self.EPS_END = 0.5
        self.steps_done = 0
        self.EPS_DECAY = 200
        self.output_size = env.action_space.n
        self.d_len = 10000
        self.dq = deque(maxlen=self.d_len)

        with tf.variable_scope(name_or_scope="placeholder", reuse=tf.AUTO_REUSE):
            self.x_input = tf.placeholder(tf.float32, shape=(None, 147), name="input")
            self.target = tf.placeholder(tf.float32, shape=(None,), name="target")
            self.actions = tf.placeholder(tf.int32, shape=(None,), name="actions")

        # we need to define two network policy and target network where target is freeze

        self.policy_network_output, self.policy_network_param = self.architecture("policyNetwork")
        self.target_network_output, self.target_network_param = self.architecture("targetNetwork")

        # shfiting of the weights
        # we need to shift the weight from policy to target

        tau = 0.001
        self.copy_weight = []
        for target, source in zip(self.target_network_param, self.policy_network_param):
            self.copy_weight.append(target.assign(target * (1 - tau) + source * tau))

        self.copy_weight = tf.group(*self.copy_weight)

    def weightMatrix(self, name):
        with tf.variable_scope(name_or_scope=name, reuse=False):
            # defining the weights for it
            self.dense1 = tf.get_variable(name="dense1", shape=(147, 128), initializer=tf.initializers.variance_scaling)
            self.dense2 = tf.get_variable(name="dense2", shape=(128, 256), initializer=tf.initializers.variance_scaling)
            self.dense3 = tf.get_variable(name="dense3", shape=(256, 128), initializer=tf.initializers.variance_scaling)
            self.dense4 = tf.get_variable(name="dense4", shape=(128, 128), initializer=tf.initializers.variance_scaling)
            # Separating streams into advantage and value networks
            self.dense_adv_net = tf.get_variable(name="adv_net", shape=(128, self.output_size), initializer=tf.initializers.variance_scaling)
            self.dense_val_net = tf.get_variable(name="val_net", shape=(128, 1), initializer=tf.initializers.variance_scaling)

    def architecture(self, name):

        # first call the architecture
        self.weightMatrix(name)
        with tf.variable_scope(name, reuse=False):
            self.dense = tf.matmul(self.x_input, self.dense1)
            self.dense = tf.nn.relu(self.dense)

            self.dense = tf.matmul(self.dense, self.dense2)
            self.dense = tf.nn.relu(self.dense)

            self.dense = tf.matmul(self.dense, self.dense3)
            self.dense = tf.nn.relu(self.dense)

            self.dense = tf.matmul(self.dense, self.dense4)
            self.dense = tf.nn.relu(self.dense)

            # Separating streams into advantage and value networks
            self.adv_net = tf.matmul(self.dense, self.dense_adv_net)
            self.adv_net = tf.nn.relu(self.adv_net)

            self.val_net = tf.matmul(self.dense, self.dense_val_net)
            self.val_net = tf.nn.relu(self.val_net)

            self.output = self.val_net + (self.adv_net - tf.reduce_mean(self.adv_net, reduction_indices=1,
                                                                             keepdims=True))

            #self.output = tf.matmul(self.dense, self.dense4)

            trainable_param = tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES, name)

            return self.output, trainable_param

    def act(self, state):
        # to get what action to choose

        # we need to do exploration vs exploitation

        eps_threshold = self.EPS_END + (self.EPS_START - self.EPS_END) * \
                        math.exp(-1. * self.steps_done / self.EPS_DECAY)
        self.steps_done += 1
        action = None
        action_ = None
        if np.random.rand() < eps_threshold:

            action = env.action_space.sample()

        else:

            action_ = self.policy_network_output.eval(feed_dict={self.x_input: state})[0]
            action = np.argmax(action_)

        return action

    def huberLoss(self, a, b):
        error = a - b
        result = tf.cond(tf.reduce_mean(tf.math.abs(error)) > 1.0, lambda: tf.math.abs(error) - 0.5,
                         lambda: error * error / 2)
        return result

    def loss(self):

        # we need to substract the target from the actual Q values
        q_sa = tf.reduce_sum(self.policy_network_output * tf.one_hot(self.actions, self.output_size), axis=-1)
        # now we can substract this value from the target value

        self.loss = self.huberLoss(self.target, q_sa)
        self.loss = tf.reduce_mean(self.loss)

        # we only want to use policy network
        self.grad = tf.gradients(self.loss, self.policy_network_param)

        # once i have the gradient wrt to policy net we can apply to network
        # but to deal with exploding gradient we perform gradient clipping

        clipped_grad = []
        for val in self.grad:
            clipped_grad.append(tf.clip_by_value(val, clip_value_min=-1, clip_value_max=1))

        # now we can apply the clipped grad values

        self.optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.005)
        self.optimizer = self.optimizer.apply_gradients(zip(clipped_grad, self.policy_network_param))

    def rememember(self, nextObservation, action, reward, observation, done):
        experiance = nextObservation, reward, action, observation, done
        self.memory_class.store(experiance)

    # def storeData(self,nextObservation,action,reward,observation,done):
    #     if self.d_len - len(self.dq) <=0:
    #         self.dq.pop()

    #     # now we can store the data
    #     self.dq.append((nextObservation,action,reward,observation,done))

    def sampleData(self):

        idx, minibatch, isWeight = self.memory_class.sample(self.batch_size)
        return idx, minibatch, isWeight

    def getData(self, batch_size):
        data = None
        if len(self.dq) > batch_size:
            data = random.sample(self.dq, batch_size)

        return data


class parser:
    def __init__(self):
        # parser to parse the ltlf formula
        self.states = {"q1","q2","q3"}
        self.initialState  = "q1"
        self.finalState    = "q3"
        self.transitions()

    def transitions(self):

        self.transition = {
			("q1","q1"):-1,
			("q1","q2"):10,
			("q2","q2"):10,
			("q2","q3"):100,
			("q3","q3"):0
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
            done = True
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
                intrinsic_reward = -10

        return intrinsic_reward,done


def preprocessing(image):
	return image.reshape(-1,147)


dqn = DDQN()
RA = parser()

dqn.loss()

key_door = []

updateNetwork = 4
game_loss = 0


with tf.Session(config=config) as sess:
    sess.run(tf.global_variables_initializer())
    # Saver will help us to save our model
    saver = tf.train.Saver()

    with open("models_dueling/dresults.txt", "w") as f:
        f.write("Ep num \t Loss \t Reward \t Intrinsic Reward \n ")
        f.close()

    for each_epispode in range(50000):
        obs  = env.reset()["image"]
        obs  = preprocessing(obs)
        done = False
        in_trinsic  = 0
        counter  = 0
        total_reward_per_episode, total_loss_per_episode = 0, 0
        steps_episode = 0
        while not done:
            #plt.imshow(env.render())
            action = dqn.act(obs)

            open_door = env.door.is_open

            if env.carrying == None:
                key = False
            else:
                key = True

            intrinsic_reward,failDfa = RA.trace(key,open_door)

            in_trinsic += intrinsic_reward

            nextObservation,reward,done,_ = env.step(action)
            reward = reward*10
            nextObservation = nextObservation["image"]
            total_reward = reward + intrinsic_reward
            done = failDfa

            dqn.rememember(preprocessing(nextObservation), action, total_reward, obs, done)

            obs = preprocessing(nextObservation)

            total_reward_per_episode += reward

            if dqn.memory_class.sumtree.total_priority() > 1000 and dqn.memory_class.sumtree.total_priority() % updateNetwork== 0:
                # we gonna update

                # retreive the data

                t_rewards ,t_dones,t_obs,t_nextObservations,t_actions = [],[],[],[],[]
                idx, minibatch, ISWeights = dqn.sampleData()

                for n_obs, n_reward, n_act, nObs, n_done in minibatch:
                    t_rewards.append(n_reward)
                    t_dones.append(n_done)
                    t_obs.append(nObs)
                    t_nextObservations.append(n_obs)
                    t_actions.append(n_act)

                t_rewards = np.array(t_rewards)
                t_dones = np.array(t_dones)
                t_obs = np.squeeze(np.array(t_obs))
                t_nextObservations = np.squeeze(np.array(t_nextObservations))
                t_actions = np.array(t_actions)

                # now we have all the mini batch we can first define our target
                # we need to send nextObservation

                t_output = dqn.target_network_output.eval(feed_dict={dqn.x_input:t_nextObservations})

                target  = []

                for i in range(len(t_output)):
                    target.append(t_rewards[i] + dqn.discount*np.max(t_output[i])*(1-t_dones[i]))

                target = np.array(target)

                game_loss, _ = sess.run([dqn.loss, dqn.optimizer],
                                       feed_dict={dqn.x_input: t_obs, dqn.actions: t_actions, dqn.target: target})

                total_loss_per_episode += game_loss

            if counter > 1000:
                sess.run(dqn.copy_weight)
                counter = 0
            counter += 1
            steps_episode += 1

        # Save model every 5 episodes
        if each_epispode % 500 == 0:
            save_path = saver.save(sess, "models_dueling/dmodel.ckpt")
            print("Model Saved")

        # Saving results into txt
        with open("models_dueling/dresults.txt", "a") as f:
            f.write(str(each_epispode)+"\t\t"+str(round(total_loss_per_episode/steps_episode,4))+"\t\t"+str(round(total_reward_per_episode,2))+"\t\t"+str(round(in_trinsic,2))+"\n")
            f.close()

        if each_epispode !=0 and each_epispode % 20 == 0:
            print("After episode ",str(each_epispode)," the game loss is ",str(game_loss)," and reward is ",str(total_reward_per_episode))
            print("Intrinsic Reward ",str(in_trinsic))