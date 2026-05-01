#include <lib/parlaylib/include/parlay/sequence.h>
#include <lib/parlaylib/include/parlay/primitives.h>
#include <atomic>
#include <list>
#include <cmath>


struct bst_node {
    int value;
    bst_node* left;
    bst_node* right;
    bst_node(int val) : value(val), left(nullptr), right(nullptr) {}
};

struct skew_node {
    uint32_t value;
    skew_node* next;
    bst_node* complete_bst;
    bst_node* leftmost;
    skew_node(uint32_t val) : value(val), next(nullptr), complete_bst(nullptr), leftmost(nullptr) {}
};

class skew_list {
    public:
        skew_node* head;
        skew_node* tail;
        size_t size;
        skew_list() : head(nullptr), tail(nullptr), size(0) {}
        
        ~skew_list() {
            while (!is_empty()) {
                pop();
            }
        }
        
        skew_list(skew_list&& other) noexcept : head(other.head), tail(other.tail), size(other.size) {
            other.head = nullptr;
            other.tail = nullptr;
            other.size = 0;
        }
        
        skew_list& operator=(skew_list&& other) noexcept {
            if (this != &other) {
                while (!is_empty()) pop(); // Clean current
                head = other.head;
                tail = other.tail;
                size = other.size;
                other.head = nullptr;
                other.tail = nullptr;
                other.size = 0;
            }
            return *this;
        }
        
        void push(uint32_t x) {
            skew_node* new_node = new skew_node(x);
            if (head == nullptr) {
                head = new_node;
                tail = new_node;
            }
            else {
                new_node->next = head;
                head = new_node;
            }
            ++size;
        }
        
        void add_back(skew_list& other) {
            if (other.head == nullptr) return;
            if (head == nullptr) {
                head = other.head;
                tail = other.tail;
            }
            else {
                tail->next = other.head;
                tail = other.tail;
            }
            size += other.size;
            other.head = nullptr;
            other.tail = nullptr;
            other.size = 0;
        }
        
        void pop(){
            if (head != nullptr) {
                skew_node* temp = head;
                head = head->next;
                if (temp == tail) {
                    tail = nullptr;
                }
                delete temp;
                --size;
            }
        }
        
        bool is_empty() {
            return head == nullptr;
        }
};

// does this return a copy
skew_list skew_init(uint32_t x) {
    skew_list l;
    if (x == 0) return l;
    uint32_t i = static_cast<uint32_t>(std::ceil(std::log2(x)));
    while (x > 0) {
        uint32_t push_val = (2 << i) - 1;
        if (2 * push_val == x) {
            l.push(push_val);
            l.push(push_val);
            break;
        }
        else if (push_val <= x) {
            l.push(push_val);
            x -= push_val;
        }
        i -= 1;
    }
    return l;
}

void skew_add(skew_list& a, uint32_t x) {
    if (a.is_empty())
        a = std::move(skew_init(x));
        return;
    uint32_t w1 = a.head->value;
    while (x >= w1) {
        bool flag = true;
        if (a.size > 1) {
            uint32_t w2 = a.head->next->value;
            if (w1 == w2) {
                a.pop(), a.pop();
                a.push(1 + w1 + w2);
                x -= 1;
                flag = false;
            }
        }
        if (flag) {
            w1 = a.head->value;
            a.pop();
            x -= w1;
        }
        w1 = a.head->value;
    }
    if (a.size > 1) {
        w1 = a.head->value;
        uint32_t w2 = a.head->next->value;
        while (w1 == w2 && x > 0) {
            a.pop(), a.pop();
            a.push(1 + w1 + w2);
            x -= 1;
            w1 = a.head->value;
            w2 = a.head->next->value;
        }
    }
    if (x > 0) {
        skew_list l = skew_init(x);
        a.add_back(l);
    }
    // this should probably become a void since we're changing a in place, or we should
    // make a copy of a to start?
}







