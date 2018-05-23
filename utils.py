# coding=utf8
import random
import torch
import torch.optim as optim
from torch.autograd import Variable

from modules.constructor import make_base_model


class Task(object):
    def __init__(self, config):
        self.config = config
        self.train_loader = None
        self.valid_loader = None
        self.optimizer = None
        self.epoch = 0
        self.enc_vocab = None
        self.dec_vocab = None
        self.model = None

    def load(self, mode='train', model_path=None, epoch=0):
        self.model_path = model_path
        if model_path is not None:
            # 加载词表存档
            self.__load_vocab()

        if mode is 'train':
            self.mode = 'train'
            self.epoch = epoch
            self.__load_data()
            self.__load_model()
            self.__load_optimizer()
        else:
            self.mode = 'test'
            self.__load_model()

    def save(self, path):
        pass

    def __load_data(self):
        # 加载文本数据
        dataset = DataSet(self.config)
        if self.enc_vocab is None or self.dec_vocab is None:
            # 创建词表
            self.enc_vocab, self.dec_vocab = dataset.build_vocabulary()
        self.train_loader, self.valid_loader = dataset.build_data_loader(self.enc_vocab, self.dec_vocab)

    def __load_optimizer(self):
        assert self.model is not None
        self.params = [p for p in self.model.parameters() if p.requires_grad]

        optim_method = self.config['train']['optim']
        learning_rate = self.config['train']['learning_rate']
        if optim_method == 'sgd':
            self.optimizer = optim.SGD(self.params, lr=learning_rate)
        elif optim_method == 'adagrad':
            self.optimizer = optim.Adagrad(self.params, lr=learning_rate)
        elif optim_method == 'adadelta':
            self.optimizer = optim.Adadelta(self.params, lr=learning_rate)
        elif optim_method == 'adam':
            # self.optimizer = optim.Adam(self.params, lr=learning_rate, betas=[0.9, 0.98], eps=1e-9)
            self.optimizer = optim.Adam(self.params, lr=learning_rate)
        else:
            raise RuntimeError("Invalid optim method: " + optim_method)

    def __load_vocab(self):
        assert self.model_path is not None
        # 根据路径加载词表

    def __load_model(self, model_path=None):
        assert self.enc_vocab and self.dec_vocab
        self.model = make_base_model(self.config['model'], len(self.enc_vocab), len(self.dec_vocab))
        if self.CUDA:
            self.model.cuda()
        if model_path is not None:
            self.model.load_state_dict(torch.load(model_path))
        

def read_dataset(file_path):
    def read_txt(data_path):
        assert os.path.exists(data_path)
        with open(data_path) as file:
            data_lines = [line[:-1].split() for line in file]
        return data_lines
    # 合并src和tgt
    return list(zip(
        read_txt(f'{file_path}.src'),
        read_txt(f'{file_path}.tgt')
    ))


class DataSet(object):
    def __init__(self, config):
        self.file_path = '/'.join([config['dataset']['path'],
                                   config['dataset']['dir'],
                                   config['dataset']['name']])
        self.MIN_LEN = config['preproccess']['min_len']
        self.MAX_LEN = config['preproccess']['max_len']
        self.MIN_COUNT = config['preproccess']['min_count']
        self.BATCH_SIZE = config['train']['batch_size']
        self.N_TEST_BATCH = config['preproccess']['n_test_batch']
        self.CUDA = config['train']['cuda']
        # 加载原始数据
        length_range = range(self.MIN_LEN, self.MAX_LEN + 1)
        def keep_pair(pair):
            return len(pair[0]) in length_range and len(pair[1]) in length_range
        self.data_pair = filter(keep, read_dataset(self.file_path))

    def build_vocabulary(self):
        enc_vocab = Vocabulary(self.config['token'])
        dec_vocab = Vocabulary(self.config['token'])
        for src_sen, tgt_sen in self.data_pair:
            for word in src_sen:
                enc_vocab.insert_word(word)
            for word in tgt_sen:
                dec_vocab.insert_word(word)
        enc_vocab.trim(self.MIN_COUNT)
        tgt_vocab.trim(self.MIN_COUNT)
        return enc_vocab, dec_vocab

    def build_data_loader(self, enc_vocab, dec_vocab):
        def word2num(pair):
            return tuple(
                [enc_vocab.word2idx[w] if w in enc_vocab.word2idx else enc_vocab.UNK for w in pair[0]],
                [dec_vocab.word2idx[w] if w in dec_vocab.word2idx else dec_vocab.UNK for w in pair[1]]
            )
        # 字符序列转成数值序列
        seq_pair = map(word2num, self.data_pair)

        # 过滤掉UNK过多的句子
        # seq_pair = filter(lambda pair: pair[0].count(enc_vocab.UNK) < 3 and pair[1].count(dec_vocab.UNK) < 2, seq_pair)
        
        # 划分批数据
        random.shuffle(seq_pair)
        num_batch = len(seq_pair) // self.BATCH_SIZE
        batch_data = [seq_pair[i: i + self.BATCH_SIZE] for i in range(0, num_batch, self.BATCH_SIZE)]

        # 填充数据
        def fill_batch(pair_batch):
            # 按src长度降序
            sorted_pair_batch = sorted(pair_batch, key=lambda x: len(x[0]), reverse=True)
            src_batch, tgt_batch = list(zip(*sorted_pair_batch))
            max_src_len = len(src_batch[0])
            max_tgt_len = max([len(x) for x in tgt_batch])
            # 填充字符
            src_batch = map(lambda x: x + [enc_vocab.EOS] + [enc_vocab.PAD] * (max_src_len - len(x)), src_batch)
            tgt_batch = map(lambda x: [dec_vocab.GO] + x + [dec_vocab.EOS] + [dec_vocab.PAD] * (max_tgt_len - len(x)), tgt_batch)
            return list(zip(src_batch, tgt_batch))
        batch_data = map(fill_batch, batch_data)
        
        # 划分数据
        self.train_loader = DataLoader(batch_data[:-self.N_TEST_BATCH], self.CUDA)
        self.valid_loader = DataLoader(batch_data[-self.N_TEST_BATCH:], self.CUDA)
        return self.train_loader, self.valid_loader


class DataLoader(object):
    def __init__(self, batch_data, CUDA=False):
        self.CUDA = CUDA
        self._variable = False
        self._batch_data = batch_data
        self._size = len(batch_data)
        # 计算每个批的src长度
        self._batch_src_length = map(lambda b: [len(x) for x in list(zip(*b))[0]], batch_data)

    def variable(self):
        if self._variable is False:
            def cnv2var(batch):
                src_batch, tgt_batch = list(zip(*self._batch_data))
                return tuple(
                    Variable(torch.LongTensor(src_batch).transpose(0, 1)),
                    Variable(torch.LongTensor(tgt_batch).transpose(0, 1))
                )
            self._batch_data = map(cnv2var, self._batch_data)
        self._variable = True

    def shuffle(self):
        random.shuffle(self._batch_data)

    def __len__(self):
        return self._size

    def __getitem__(self, index):
        src_batch, tgt_batch = list(zip(*self._batch_data[index]))
        if self._variable is True:
            src_batch = Variable(torch.LongTensor(src_batch).transpose(0, 1))
            tgt_batch = Variable(torch.LongTensor(tgt_batch).transpose(0, 1))

        if self.CUDA:
            return src_batch.cuda(), tgt_batch.cuda(), self._batch_src_length[index]
        return src_batch, tgt_batch, self._batch_src_length[index]

class Vocabulary(object):
    def __init__(self, TOKEN):
        self.PAD = TOKEN['PAD']
        self.GO = TOKEN['GO']
        self.EOS = TOKEN['EOS']
        self.UNK = TOKEN['UNK']
        self.reset()

    def reset(self):
        self.word2count = {}
        self.word2idx = {
            'PAD': self.PAD,
            'GO': self.GO,
            'EOS': self.EOS,
            'UNK': self.UNK,
        }
        self.idx2word = dict(zip(self.word2idx.values(), self.word2idx.keys()))
        self.n_words = len(self.word2idx)

    def __len__(self):
        return len(self.word2idx)

    def insert_word(self, word):
        if word not in self.word2count:
            self.word2idx[word] = self.n_words
            self.idx2word[self.n_words] = word
            self.word2count[word] = 1
            self.n_words += 1
        else:
            self.word2count[word] += 1
    
    def trim(self, min_count):
        keep_word = filter(lambda w: self.word2count[w] >= min_count, self.word2count.keys())

        self.reset()
        for word in keep_word:
            self.insert_word(word)

    def save(self, path):
        pass


