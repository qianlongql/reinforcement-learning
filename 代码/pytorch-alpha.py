import sys
import argparse
import random
import math
import numpy as np
from collections import namedtuple, deque
import matplotlib.pyplot as plt

import gym
from gym import wrappers

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torchvision.transforms as T
from numpy.core._multiarray_umath import ndarray
from torch.autograd import Variable

import pdb
from cv2 import resize
from skimage.color import rgb2gray

# if gpu is to be used
use_cuda = torch.cuda.is_available()
FloatTensor = torch.cuda.FloatTensor if use_cuda else torch.FloatTensor
LongTensor = torch.cuda.LongTensor if use_cuda else torch.LongTensor

Transition = namedtuple('Transition', ('state', 'action', 'next_state', 'reward'))


class Space_Invaders_CNN(nn.Module):
    def __init__(self):
        super(Space_Invaders_CNN, self).__init__()
        self.conv1 = nn.Conv2d(3, 32, 8, stride=4)
        self.conv2 = nn.Conv2d(32, 64, 4, stride=2)
        self.conv3 = nn.Conv2d(64, 64, 3, stride=1)
        self.fc1 = nn.Linear(3136, 512)
        self.fc2 = nn.Linear(512, 6)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.relu(self.conv3(x))
        x = x.view(-1, 3136)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x


class LinearQN(nn.Module):
    def __init__(self, n_in, n_out):
        super(LinearQN, self).__init__()
        self.fc = nn.Linear(n_in, n_out)

    def forward(self, x):
        x = self.fc(x)
        return x


class DQN(nn.Module):
    def __init__(self, n_in, n_hidden, n_out):
        super(DQN, self).__init__()
        self.fc1 = nn.Linear(n_in, n_hidden)
        self.fc2 = nn.Linear(n_hidden, n_hidden)
        self.fc3 = nn.Linear(n_hidden, n_hidden)
        self.fc4 = nn.Linear(n_hidden, n_out)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        x = self.fc4(x)
        return x


class DuelingDQN(nn.Module):
    def __init__(self, n_in, n_hidden, n_out):
        super(DuelingDQN, self).__init__()
        self.n_actions = n_out

        self.fc1 = nn.Linear(n_in, n_hidden)
        self.fc2 = nn.Linear(n_hidden, 2 * n_hidden)

        self.fc1_adv = nn.Linear(2 * n_hidden, n_hidden)
        self.fc1_val = nn.Linear(2 * n_hidden, n_hidden)

        self.fc2_adv = nn.Linear(n_hidden, self.n_actions)
        self.fc2_val = nn.Linear(n_hidden, 1)

    def forward(self, x):
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))

        adv = F.relu(self.fc1_adv(x))
        val = F.relu(self.fc1_val(x))

        adv = self.fc2_adv(adv)
        val = self.fc2_val(val).expand(x.size(0), self.n_actions)

        x = val + adv - adv.mean(1).unsqueeze(1).expand(x.size(0), self.n_actions)
        return x


class ReplayMemory(object):
    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def store(self, *args):
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = Transition(*args)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


class Agent(object):
    def __init__(self, args, render=False):
        self.env = gym.make(args.env)
        # self.env = gym.wrappers.Monitor(self.env, directory='monitors/'+args.env, force=True)
        # n_in = self.env.observation_space.shape[0]
        # n_out = self.env.action_space.n
        self.batch_size = args.batch_size

        # type of function approximator to use
        if args.model_type == 'Space_Invaders_CNN':
            self.model = Space_Invaders_CNN()
        elif args.model_type == 'linear':
            self.model = LinearQN(args.n_in, args.n_out)
        elif args.model_type == 'dqn':
            self.model = DQN(args.n_in, args.n_hidden, args.n_out)
        else:
            self.model = DuelingDQN(args.n_in, args.n_hidden, args.n_out)

        if use_cuda:
            self.model.cuda()

        # should experience replay be used
        if args.exp_replay:
            self.exp_replay = True
            self.memory = ReplayMemory(args.buffer_size)
        else:
            # memory of size 1 is same as using only the immediate transitions
            # this is only to keep the overall api similar for all cases
            self.memory = ReplayMemory(1)
            assert self.batch_size == 1

        # policy type
        if args.eps_greedy:
            self.eps_greedy = True
            self.eps_start = args.eps_start
            self.eps_end = args.eps_end
            self.eps_decay = args.eps_decay
        else:
            self.eps_greedy = False

        if args.optimizer == 'rmsprop':
            self.optimizer = optim.RMSprop(self.model.parameters())
        else:
            self.optimizer = optim.Adam(self.model.parameters(), lr=args.lr)

        self.gamma = args.gamma
        self.num_episodes = args.num_episodes
        self.loss_fn = args.loss_fn
        self.steps_done = 0
        self.episode_durations = []
        self.test_rewards = []
        self.memory_burn_limit = args.memory_burn_limit
        self.curr_rewards = []
        # pdb.set_trace()

    def select_action(self, state, train):
        state = FloatTensor(state)
        if train:
            self.steps_done += 1
        # action will be selected based on the policy type : greedy or epsilon-greedy
        if self.eps_greedy:
            # smoothly decaying the epsilon threshold value as we progress
            if train:
                # eps_threshold = self.eps_end + (self.eps_start - self.eps_end) * math.exp(-1.*(self.steps_done/self.eps_decay))
                eps_threshold = (self.steps_done) * (
                            (self.eps_end - self.eps_start) / (self.eps_decay)) + self.eps_start
            else:
                eps_threshold = 0.05
            # explore or exploit?
            if random.random() > eps_threshold:
                return self.model(Variable(state, volatile=True).type(FloatTensor)).data.max(1)[1].view(1, 1)
                # with torch.no_grad():
                #    action = self.model(Variable(state))
                # return action.data.max(1)[1].view(1,1)
            else:
                return LongTensor([[random.randrange(self.env.action_space.n)]])
                # return LongTensor([[random.randrange(2)]])
        else:
            return self.model(Variable(state, volatile=True).type(FloatTensor)).data.max(1)[1].view(1, 1)
            # with torch.no_grad():
            #    action = self.model(Variable(state))
            # return action.data.max(1)[1].view(1,1)

    def burn_memory(self):

        steps = 0
        state = np.zeros((3, 84, 84))
        next_state = np.zeros((3, 84, 84))

        state_single = self.env.reset()
        state_single = rgb2gray(state_single)
        state_single = state_single[50:210, 0:160]
        state_single = resize(state_single, (84, 84))

        state[0, :, :] = state_single
        state[1, :, :] = state_single
        state[2, :, :] = state_single

        print('Starting to fill the memory with random policy')
        while steps < self.memory_burn_limit:

            # Executing a random policy
            action = LongTensor([[random.randrange(self.env.action_space.n)]])
            next_state_single, reward, is_terminal, _ = self.env.step(action[0, 0])
            next_state_single = rgb2gray(next_state_single)
            next_state_single = next_state_single[50:210, 0:160]
            next_state_single = resize(next_state_single, (84, 84))
            for i in range(84):
                for j in range(84):
                    next_state_single[i, j] = max(state_single[i, j], next_state_single[i, j])
            next_state[0, :, :] = state[1, :, :]
            next_state[1, :, :] = state[2, :, :]
            next_state[2, :, :] = next_state_single

            # self.memory.store(FloatTensor([state]),
            #                  action,
            #                  FloatTensor([next_state]),
            #                  FloatTensor([reward]))

            if is_terminal:
                # store the transition in memory

                self.memory.store(FloatTensor([state]),
                                  action,
                                  None,
                                  FloatTensor([reward]))
            else:
                self.memory.store(FloatTensor([state]),
                                  action,
                                  FloatTensor([next_state]),
                                  FloatTensor([reward]))

            steps += 1
            state = next_state

            while steps == self.memory_burn_limit and not is_terminal:
                #Executing a random policy
                action = LongTensor([[random.randrange(self.env.action_space.n)]])
                next_state, reward, is_terminal, _ = self.env.step(action[0,0])

            # If the next_state is terminal, then you reset it
            if is_terminal:
                state_single = self.env.reset()
                state_single = rgb2gray(state_single)
                state_single = state_single[50:210, 0:160]
                state_single = resize(state_single, (84, 84))

                state[0, :, :] = state_single
                state[1, :, :] = state_single
                state[2, :, :] = state_single


        print('Memory filled, ready to start training now')
        print("-" * 50)

    ################################################################################################################################################
    def testing_random_play(self):

        state = self.env.reset()
        state = rgb2gray(state)
        state = state[50:210, 0:160]
        state = resize(state, (84, 84))
        # state is 210,160,3

        for i in range(1000):
            # action = random.randrange(self.env.action_space.n)
            action = LongTensor([[random.randrange(self.env.action_space.n)]])
            next_state, reward, is_terminal, _ = self.env.step(action[0, 0])
            print(reward, is_terminal)
            self.env.render()
        print('Random play done now')

    ################################################################################################################################################

    def play_episode(self, e, train=True):

        state_single = self.env.reset()

        state_single = rgb2gray(resize(state_single, (84, 84)))

        state = np.zeros((3, 84, 84))
        next_state = np.zeros((3, 84, 84))

        state[0, :, :] = state_single
        state[1, :, :] = state_single
        state[2, :, :] = state_single

        steps = 0
        total_reward = 0
        # iterate till the terminal state is reached
        while True:
            self.env.render()
            action = self.select_action([state], train)
            # print("action: ", action)
            next_state_single, reward, is_terminal, _ = self.env.step(action[0, 0])
            next_state_single = rgb2gray(next_state_single)
            next_state_single = next_state_single[50:210, 0:160]
            next_state_single = resize(next_state_single, (84, 84))
            for i in range(84):
                for j in range(84):
                    next_state_single[i, j] = max(state_single[i, j], next_state_single[i, j])
            next_state[0, :, :] = state[1, :, :]
            next_state[1, :, :] = state[2, :, :]
            next_state[2, :, :] = next_state_single

            total_reward += reward

            if is_terminal:
                # store the transition in memory
                next_state = None
                self.memory.store(FloatTensor([state]),
                                  action,
                                  None,
                                  FloatTensor([reward]))
            else:
                self.memory.store(FloatTensor([state]),
                                  action,
                                  FloatTensor([next_state]),
                                  FloatTensor([reward]))

            if train:
                # backprop and learn; otherwise just play the policy
                self.optimize_model()
            # update state
            state = next_state
            steps += 1
            if is_terminal:
                if train:
                    # backprop and learn; otherwise just play the policy
                    # self.optimize_model()
                    # if steps %20 == 0:
                    print("Episode {} completed after {} steps | Total steps = {} | reward = {} ".format(e, steps, self.steps_done, total_reward))
                self.episode_durations.append(steps)
                # self.plot_durations()
                return total_reward

    def optimize_model(self):
        # check if enough experience collected so far
        # the agent continues with a random policy without updates till then
        if len(self.memory) < self.batch_size:
            return

        self.optimizer.zero_grad()
        # sample a random batch from the replay memory to learn from experience
        # for no experience replay the batch size is 1 and hence learning online
        transitions = self.memory.sample(self.batch_size)
        batch = Transition(*zip(*transitions))
        # isolate the values
        non_terminal_mask = np.array(list(map(lambda s: s is not None, batch.next_state)))
        # with torch.no_grad():
        #     batch_next_state = Variable(torch.cat([s for s in batch.next_state if s is not None]))
        batch_next_state = Variable(torch.cat([s for s in batch.next_state if s is not None]), volatile=True)
        # batch_next_state = Variable(torch.cat(batch.next_state))

        batch_state = Variable(torch.cat(batch.state))
        batch_action = Variable(torch.cat(batch.action))
        batch_reward = Variable(torch.cat(batch.reward))

        # There is no separate target Q-network implemented and all updates are done
        # synchronously at intervals of 1 unlike in the original paper
        # current Q-values
        current_Q = self.model(batch_state).gather(1, batch_action)
        # expected Q-values (target)
        max_next_Q = self.model(batch_next_state).detach().max(1)[0]
        expected_Q = torch.tensor(batch.reward)
        if use_cuda:
            expected_Q[non_terminal_mask] += (self.gamma * max_next_Q).cpu().data
            # with torch.no_grad():
            # expected_Q = Variable(torch.from_numpy(expected_Q).cuda())

        else:
            expected_Q[non_terminal_mask] += (self.gamma * max_next_Q).data
            expected_Q = Variable(torch.from_numpy(expected_Q), volatile=True)
        # expected_Q = batch_reward + (self.gamma * max_next_Q)
        # expected_Q = batch_reward + (self.gamma * max_next_Q)

        # loss between current Q values and target Q values
        expected_Q = expected_Q.cuda()
        if self.loss_fn == 'l1':
            loss = F.smooth_l1_loss(current_Q, expected_Q)
        else:
            loss = F.mse_loss(current_Q, expected_Q)

        # backprop the loss
        loss.backward()
        self.optimizer.step()

    def plot_durations(self):
        durations = torch.FloatTensor(self.episode_durations)
        plt.figure(1)
        plt.clf()
        plt.title('Training')
        plt.xlabel('Episode')
        plt.ylabel('Duration')
        plt.plot(durations.numpy())
        # Averaging over 100 episodes and plotting those values
        if len(durations) >= 100:
            means = durations.unfold(0, 100, 1).mean(1).view(-1)
            means = torch.cat((torch.zeros(99), means))
            plt.plot(means.numpy())
        # pause so that the plots are updated
        plt.pause(0.001)

    def plot_rewards(self):
        plt.figure(2)
        plt.clf()
        plt.title('Test')
        plt.ylabel('Test Reward')
        plt.plot(self.test_rewards)
        # pause so that the plots are updated
        plt.pause(0.001)
        # plt.show()

    def plot_curr_rewards(self):
        plt.figure(3)
        plt.clf()
        plt.title('Training')
        plt.ylabel('reward')
        plt.plot(self.curr_rewards)
        plt.pause(0.001)

    def train(self, all_step):
        print("Going to be training for a total of {} episodes".format(all_step))
        for e in range(all_step):
            print("----------- Episode {} -----------".format(e))
            reward = self.play_episode(e, train=True)
            self.curr_rewards.append(reward)
            self.plot_curr_rewards()
            self.plot_durations()
            # if e % self.target_update == 0:
            # self.target.load_state_dict(self.model.state_dict())
            if e % 50 == 0:
                self.test(2)

    def test(self, num_episodes):
        total_reward = 0
        print("-" * 50)
        print("Testing for {} episodes".format(num_episodes))
        for e in range(num_episodes):
            total_reward = self.play_episode(e, train=False)
            self.test_rewards.append(total_reward)
        print("Running policy after training for {} updates".format(self.steps_done))
        print("Avg reward achieved in {} episodes : {}".format(num_episodes, total_reward / num_episodes))
        print("-" * 50)
        self.plot_rewards()

    def close(self):
        self.env.render()
        self.env.close()
        plt.ioff()
        plt.show()


def parse_arguments():
    parser = argparse.ArgumentParser(description='Deep Q Network Argument Parser')
    parser.add_argument('--env', type=str, default='SpaceInvaders-v0')
    parser.add_argument('--render', type=int, default=0)
    parser.add_argument('--model_type', type=str, default='Space_Invaders_CNN',
                        help='Model type one of (linear,dqn,duel)')
    parser.add_argument('--exp_replay', type=int, default=1, help='should experience replay be used, default 1')
    parser.add_argument('--num_episodes', type=int, default=10, help='number of episodes')
    parser.add_argument('--batch_size', type=int, default=2, help='batch size')
    parser.add_argument('--buffer_size', type=int, default=500, help='Replay memory buffer size')
    parser.add_argument('--n_in', type=int, default=4, help='input layer size')
    parser.add_argument('--n_out', type=int, default=256, help='output layer size')
    parser.add_argument('--loss_fn', type=str, default='l2', help='loss function one of (l1,l2) | Default: l1')
    parser.add_argument('--optimizer', type=str, default='adam',
                        help='optimizer one of (rmsprop,adam) | Default : rmsprop')
    parser.add_argument('--n_hidden', type=int, default=32, help='hidden layer size')
    parser.add_argument('--gamma', type=float, default=0.99, help='discount factor')
    parser.add_argument('--lr', type=float, default=0.0001, help='learning rate')
    parser.add_argument('--frame_hist_len', type=int, default=4, help='frame history length | Default : 4')
    parser.add_argument('--eps_greedy', type=int, default=0.99, help='should policy be epsilon-greedy, default 1')
    parser.add_argument('--eps_start', type=float, default=0.95, help='e-greedy threshold start value')
    parser.add_argument('--eps_end', type=float, default=0.05, help='e-greedy threshold end value')
    parser.add_argument('--eps_decay', type=int, default=100000, help='e-greedy threshold decay')
    parser.add_argument('--logs', type=str, default='logs', help='logs path')
    parser.add_argument('--memory_burn_limit', type=int, default=20000, help='Till when to burn memory')
    return parser.parse_args()


def main():
    plt.ion()
    #plt.figure()
    #plt.show()

    args = parse_arguments()
    print(args)
    agent = Agent(args)

    # agent.testing_random_play()
    # pdb.set_trace()

    agent.burn_memory()
    # pdb.set_trace()
    agent.train(500)
    print('----------- Completed Training -----------')
    agent.test(num_episodes=100)
    print('----------- Completed Testing -----------')

    # pdb.set_trace()
    agent.close()

    plt.ioff()
    plt.show()


if __name__ == '__main__':
    main()

# TODO
# 1) Verify is this correct--->>> rgb2gray(resize(state_single,(84,84)))
# 2) Storing none for next_state if it's terminal state during burning
# 3) Check is this required in burning memory.......            #while steps == self.memory_burn_limit and not is_terminal:
# 4) Take a look at the resized images and crop the center region

