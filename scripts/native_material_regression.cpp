// Direct native material regression: return codes, copy/revert and condensation.
// Built only as the optional NativeMaterialRegression target; no structure solve.
#include <Python.h>
#include <ASDConcrete3DMaterial.h>
#include <PlateFiberMaterial.h>
#include <Parallel3DMaterial.h>
#include <Response.h>
#include <Information.h>
#include <OPS_Globals.h>
#include <Domain.h>
#include <Node.h>
#include <ShellMITC4.h>
#include <LayeredShellFiberSection.h>
#include <Channel.h>
#include <FEM_ObjectBrokerAllClasses.h>
#include <cmath>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <vector>
#include <map>
#include <iomanip>
#include <Eigen/Eigenvalues>
#include "native_material_fixture.h"

void require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
double difference(const Vector& a,const Vector& b) { Vector d(a); d.addVector(1.,b,-1.); return d.Norm(); }
double matrix_difference(const Matrix& a,const Matrix& b) {
    double sum=0.;for(int i=0;i<a.noRows();++i)for(int j=0;j<a.noCols();++j)sum+=std::pow(a(i,j)-b(i,j),2);
    return std::sqrt(sum);
}
ASDConcrete3DMaterial concrete() {
    using M=ASDConcrete3DMaterial;
    const double E=30.e9, length=0.51234753829798;
    M::HardeningLaw ht(1,M::HardeningLawType::Tension,E,{0.,2.e6/E,400./(2.e6*length)},{0.,2.e6,0.},{0.,0.,1.});
    M::HardeningLaw hc(1,M::HardeningLawType::Compression,E,{0.,12.e6/E,.002,.006},{0.,12.e6,30.e6,0.},{0.,0.,.5,1.});
    return M(1,E,.2,0.,0.,2./3.,false,false,.05,.01,1.,true,false,1.,ht,hc,0.,0,0,45.);
}
Vector strain6(const double* data) { Vector x(6); for(int i=0;i<6;++i)x(i)=data[i]; return x; }
Vector strain5(const double* data) { Vector x(5); int k[5]={0,1,3,4,5}; for(int i=0;i<5;++i)x(i)=data[k[i]]; return x; }
void replay(ASDConcrete3DMaterial& c) {
    for (auto& x:accepted_strains) { require(c.setTrialStrain(strain6(x))==0,"history trial failed"); require(c.commitState()==0,"history commit failed"); }
}
std::unique_ptr<Response> fullResponse(PlateFiberMaterial& p,const char* quantity) {
    const char* args[]={"material","1",quantity};
    return std::unique_ptr<Response>(p.setResponse(args,3,opserr));
}
Vector read(Response& r) { require(r.getResponse()==0,"response failed"); return *r.getInformation().theVector; }
Vector observed(NDMaterial& c,const char* name) {
    const char* args[]={name};std::unique_ptr<Response> r(c.setResponse(args,1,opserr));
    require(bool(r),"missing material observation");return read(*r);
}
Eigen::Matrix3d tensor(const Vector& v) {
    Eigen::Matrix3d a;a<<v(0),v(3),v(5),v(3),v(1),v(4),v(5),v(4),v(2);return a;
}
struct ConcreteBranches {
    Vector old_strain, old_hardening, te,ts,tq,ce,cs,cq;
    Matrix elastic;
    Eigen::Matrix3d effective_committed;
    explicit ConcreteBranches(ASDConcrete3DMaterial& c):old_strain(c.getStrain()),
        old_hardening(observed(c,"equivalentTotalStrain")),te(observed(c,"Te")),ts(observed(c,"Ts")),
        tq(observed(c,"Tq")),ce(observed(c,"Ce")),cs(observed(c,"Cs")),cq(observed(c,"Cq")),elastic(c.getInitialTangent()) {
        Vector damage=observed(c,"damage");
        Eigen::SelfAdjointEigenSolver<Eigen::Matrix3d> eig(tensor(c.getStress()));
        require(eig.info()==Eigen::Success,"independent stress eigenproblem failed");
        Eigen::Vector3d values=eig.eigenvalues();
        for(int i=0;i<3;++i){double w=1.-damage(values(i)>0. ? 0:1);require(w>0.,"cannot reconstruct committed effective stress");values(i)/=w;}
        effective_committed=eig.eigenvectors()*values.asDiagonal()*eig.eigenvectors().transpose();
    }
    static void law_signature(std::vector<int>& signature,double x,const Vector& e,const Vector& y,const Vector& q,double xtol,double ytol) {
        int segment=e.Size();
        for(int i=1;i<e.Size();++i)if(x<=e(i)+xtol){segment=i;break;}
        double raw_y,raw_q;
        if(segment<e.Size()) {
            double ratio=(x-e(segment-1))/(e(segment)-e(segment-1));
            raw_y=y(segment-1)+(y(segment)-y(segment-1))*ratio;
            raw_q=q(segment-1)+(q(segment)-q(segment-1))*ratio;
        } else {
            int n=e.Size()-1;double span=e(n)-e(n-1);
            raw_y=y(n)+std::max(0.,(y(n)-y(n-1))/span)*(x-e(n));
            raw_q=q(n)+std::max(0.,(q(n)-q(n-1))/span)*(x-e(n));
        }
        signature.push_back(segment);signature.push_back(raw_y>ytol);signature.push_back(raw_q>ytol);
    }
    std::vector<int> signature(const Vector& strain,const Vector& hardening)const {
        Vector delta(strain);delta.addVector(1.,old_strain,-1.);Vector ds(6);ds.addMatrixVector(0.,elastic,delta,1.);
        Eigen::SelfAdjointEigenSolver<Eigen::Matrix3d> eig(effective_committed+tensor(ds));
        require(eig.info()==Eigen::Success,"independent trial eigenproblem failed");
        auto principal=eig.eigenvalues();std::vector<int> result;
        for(int i=0;i<3;++i)result.push_back(principal(i)>0. ? 1:principal(i)<0. ? -1:0);
        result.push_back(principal(2)<2.); // frozen input ft curve stress tolerance
        result.push_back(hardening(0)>old_hardening(0));result.push_back(hardening(1)>old_hardening(1));
        law_signature(result,hardening(0),te,ts,tq,(2.e6/30.e9)*1.e-6,2.);
        law_signature(result,hardening(1),ce,cs,cq,.0004*1.e-6,12.);
        law_signature(result,hardening(0)*15.,ce,cs,cq,.0004*1.e-6,12.);
        return result;
    }
};

// Analytic adapters exercise root-search and overflow edge cases independently
// of the concrete law. They are test-only materials, never registered in models.
class ScalarTest3D : public NDMaterial {
    int mode;Vector x=Vector(6),s=Vector(6);Matrix D=Matrix(6,6);
public:
    explicit ScalarTest3D(int which):NDMaterial(91,0),mode(which) { setTrialStrain(x); }
    int setTrialStrain(const Vector& v) override {
        x=v;D.Zero();for(int i=0;i<6;++i)D(i,i)=1.;s=x;
        if(mode==1) { D(2,2)=std::numeric_limits<double>::denorm_min();D(0,2)=D(2,0)=1.;s.addMatrixVector(0.,D,x,1.); }
        else {s(2)=1.e12*x(2)*x(2)+(mode==2 ? 1. : -1.);D(2,2)=2.e12*x(2);}
        return 0;
    }
    const Vector& getStrain()override{return x;}const Vector& getStress()override{return s;}
    const Matrix& getTangent()override{return D;}
    NDMaterial* getCopy()override{return new ScalarTest3D(*this);}
    NDMaterial* getCopy(const char*)override{return getCopy();}
    int getOrder()const override{return 6;}const char* getType()const override{return "ThreeDimensional";}
    int commitState()override{return 0;}int revertToLastCommit()override{return 0;}int revertToStart()override{return 0;}
    int sendSelf(int,Channel&)override{return -1;}int recvSelf(int,Channel&,FEM_ObjectBroker&)override{return -1;}
    void Print(OPS_Stream&,int=0)override{}
};
void bracket_test() {
    ScalarTest3D c(0);PlateFiberMaterial p(92,c);Vector x(5);
    require(p.setTrialStrain(x)==0,"Plate missed brackets between seed and each same-sign endpoint");
}
void overflow_test() {
    ScalarTest3D c(1);PlateFiberMaterial p(92,c);Vector x(5);
    require(p.setTrialStrain(x)<0,"Plate accepted nonfinite condensed tangent");
}
void no_root_test() {
    ScalarTest3D c(2);PlateFiberMaterial p(92,c);Vector x(5);
    require(p.setTrialStrain(x)<0,"Plate accepted root search without a root");
}

class MemoryChannel : public Channel {
    int next=1000;
    std::map<std::pair<int,int>,Vector> vectors;
    std::map<std::pair<int,int>,ID> identifiers;
public:
    char* addToProgram()override{return nullptr;}int setUpConnection()override{return 0;}
    int setNextAddress(const ChannelAddress&)override{return 0;}
    ChannelAddress* getLastSendersAddress()override{return nullptr;}
    int getDbTag()override{return ++next;}
    int sendObj(int,MovableObject&,ChannelAddress*)override{return -1;}
    int recvObj(int,MovableObject&,FEM_ObjectBroker&,ChannelAddress*)override{return -1;}
    int sendMsg(int,int,const Message&,ChannelAddress*)override{return -1;}
    int recvMsg(int,int,Message&,ChannelAddress*)override{return -1;}
    int sendMatrix(int,int,const Matrix&,ChannelAddress*)override{return -1;}
    int recvMatrix(int,int,Matrix&,ChannelAddress*)override{return -1;}
    int sendVector(int tag,int commit,const Vector& v,ChannelAddress*)override{vectors[{tag,commit}]=v;return 0;}
    int recvVector(int tag,int commit,Vector& v,ChannelAddress*)override{v=vectors.at({tag,commit});return 0;}
    int sendID(int tag,int commit,const ID& v,ChannelAddress*)override{identifiers[{tag,commit}]=v;return 0;}
    int recvID(int tag,int commit,ID& v,ChannelAddress*)override{v=identifiers.at({tag,commit});return 0;}
};
void serialization_test() {
    FEM_ObjectBrokerAllClasses broker;
    {
        auto c=concrete();replay(c);c.setDbTag(61);
        Vector x(strain6(trial_strains[0]));require(c.setTrialStrain(x)==0,"ASD serialization trial failed");
        MemoryChannel channel;require(c.sendSelf(7,channel)==0,"ASD send failed");
        ASDConcrete3DMaterial restored;restored.setDbTag(61);require(restored.recvSelf(7,channel,broker)==0,"ASD recv failed");
        require(difference(c.getStress(),restored.getStress())==0.,"ASD trial stress transfer mismatch");
        x(0)+=1.e-6;require(c.setTrialStrain(x)==0 && restored.setTrialStrain(x)==0,"ASD subsequent trial failed");
        require(difference(c.getStress(),restored.getStress())<1.e-8,"ASD constitutive law changed after transfer");
        require(matrix_difference(c.getTangent(),restored.getTangent())<1.e-4,"ASD tangent changed after transfer");
    }
    {
        auto c=concrete();replay(c);Parallel3DMaterial wrapped(2,{&c},{1.});PlateFiberMaterial p(3,wrapped);
        Vector a(strain5(accepted_strains[9]));require(p.setTrialStrain(a)==0,"Plate serialization baseline failed");
        require(p.commitState()==0,"Plate serialization commit failed");
        Vector x(strain5(trial_strains[0]));require(p.setTrialStrain(x)==0,"Plate serialization trial failed");
        p.setDbTag(61);MemoryChannel channel;require(p.sendSelf(7,channel)==0,"Plate send failed");
        PlateFiberMaterial restored;restored.setDbTag(61);require(restored.recvSelf(7,channel,broker)==0,"Plate recv failed");
        require(difference(p.getStrain(),restored.getStrain())==0.,"Plate trial cache changed after transfer");
        require(difference(p.getStress(),restored.getStress())==0.,"Plate trial stress changed after transfer");
        require(matrix_difference(p.getTangent(),restored.getTangent())<1.e-4,"Plate tangent changed after transfer");
        require(p.revertToLastCommit()==0 && restored.revertToLastCommit()==0,"Plate transfer revert failed");
        require(difference(restored.getStrain(),a)==0.,"Plate committed cache lost in transfer");
        require(difference(p.getStress(),restored.getStress())==0.,"Plate committed stress lost in transfer");
    }
}

void state_test() {
    auto c=concrete(); replay(c);
    Vector before(c.getStress()), eps(c.getStrain()); Matrix C(c.getTangent());
    Vector x(strain6(trial_strains[0]));
    require(c.setTrialStrain(x)==0,"trial failed");
    require(c.revertToLastCommit()==0,"revert failed");
    require(difference(c.getStress(),before)<1.e-8,"ASD nominal stress not restored on revert");
    require(difference(c.getStrain(),eps)==0.,"ASD strain not restored");
    require(matrix_difference(c.getTangent(),C)<1.e-5,"ASD tangent not restored");
    Vector bad(x); bad(2)=std::numeric_limits<double>::quiet_NaN();
    require(c.setTrialStrain(bad)<0,"ASD accepted nonfinite strain");
    require(difference(c.getStress(),before)==0.,"ASD failed trial polluted state");
    Parallel3DMaterial wrapped(2,{&c},{1.}); PlateFiberMaterial p(3,wrapped);
    Vector a(strain5(accepted_strains[9]));
    require(p.setTrialStrain(a)==0,"Plate baseline failed"); require(p.commitState()==0,"Plate commit failed");
    Vector ps(p.getStress());
    std::unique_ptr<NDMaterial> cp(p.getCopy());
    require(difference(cp->getStrain(),a)==0.,"Plate getCopy lost five-component strain");
    Vector b(a);b(0)+=1.e-6;require(p.setTrialStrain(b)==0,"Plate perturbation failed");
    require(p.revertToLastCommit()==0,"Plate revert failed");
    require(difference(p.getStrain(),a)==0.,"Plate revert lost five-component strain");
    require(difference(p.getStress(),ps)<1.e-8,"Plate revert lost nominal stress");
    bad=Vector(5);bad(0)=std::numeric_limits<double>::infinity();
    require(p.setTrialStrain(bad)<0,"Plate accepted nonfinite strain");
    require(difference(p.getStrain(),a)==0.,"Plate failed trial polluted strain");
}

void root_test(bool diagnostic=false) {
    auto c=concrete(); replay(c);ConcreteBranches branches(c);
    Parallel3DMaterial wrapped(2,{&c},{1.}); PlateFiberMaterial p(3,wrapped);
    // Create responses before repeated trials: replacing/deleting the adaptee
    // during root finding would invalidate these recorder-bound pointers.
    auto stress=fullResponse(p,"stress"), strain=fullResponse(p,"strain");
    auto hardening=fullResponse(p,"equivalentTotalStrain");
    require(stress && strain,"cannot observe full material");
    int point=0;
    for (auto& trial:trial_strains) {
        Vector x(strain5(trial));require(p.setTrialStrain(x)==0,"Plate rejected saved solvable trial");
        Vector sx=read(*stress), ex=read(*strain);
        auto base_branch=branches.signature(ex,read(*hardening));
        require(std::abs(sx(2))<=1.e-8,"Plate returned success above sigma33 tolerance");
        require(difference(p.getStrain(),x)==0.,"Plate cached strain differs");
        Matrix tangent(p.getTangent());Vector base(p.getStress());
        for (double h: (diagnostic ? std::vector<double>{1.e-7,1.e-8,1.e-9,1.e-10} : std::vector<double>{1.e-7,1.e-8}))
        for (int j=0;j<5;++j) {
            // Condensed derivatives require fresh roots; choose a displacement
            // perturbation above the absolute 1e-8 Pa root-noise floor.
            Vector plus(x);plus(j)+=h;
            require(p.setTrialStrain(plus)==0,"Plate derivative plus failed");Vector sp(p.getStress());
            double plus_sigma=read(*stress)(2);
            bool plus_branch=branches.signature(read(*strain),read(*hardening))==base_branch;
            Vector minus(x);minus(j)-=h;
            require(p.setTrialStrain(minus)==0,"Plate derivative minus failed");Vector sm(p.getStress());
            double minus_sigma=read(*stress)(2);
            bool minus_branch=branches.signature(read(*strain),read(*hardening))==base_branch;
            Vector predicted(5);for(int i=0;i<5;++i)predicted(i)=tangent(i,j);
            sp.addVector(1.,base,-1.);sp*=1./h;
            sm.addVector(-1.,base,1.);sm*=1./h;
            double pe=difference(sp,predicted)/std::max(predicted.Norm(),1.);
            double me=difference(sm,predicted)/std::max(predicted.Norm(),1.);
            if(diagnostic || pe>=.002 || me>=.002)std::cout<<std::setprecision(17)
                <<"{\"point\":"<<point<<",\"column\":"<<j<<",\"h\":"<<h<<",\"tangent_norm\":"<<predicted.Norm()
                <<",\"plus_error\":"<<pe<<",\"minus_error\":"<<me<<",\"base_sigma33\":"<<sx(2)
                <<",\"plus_sigma33\":"<<plus_sigma<<",\"minus_sigma33\":"<<minus_sigma
                <<",\"plus_branch_match\":"<<plus_branch<<",\"minus_branch_match\":"<<minus_branch<<"}\n";
            if(!diagnostic) {
                require(plus_branch && minus_branch,"condensed stencil crossed constitutive branches");
                require(pe<.002,"condensed plus derivative mismatch");
                require(me<.002,"condensed minus derivative mismatch");
            }
        }
        require(p.setTrialStrain(x)==0,"Plate final repeat failed");
        require(std::abs(read(*stress)(2))<=1.e-8,"Plate final state not balanced");
        ++point;
    }
}
void shell_failure_test() {
    // Domain::update publishes these process globals without restoring them.
    // Restore the standalone fixture's context after its local Domain dies;
    // otherwise later material tests dereference the deleted shell for lch.
    struct ActiveContext {
        Domain* domain=ops_TheActiveDomain;
        Element* element=ops_TheActiveElement;
        double dt=ops_Dt;
        ~ActiveContext() { ops_TheActiveDomain=domain;ops_TheActiveElement=element;ops_Dt=dt; }
    } active_context;
    auto c=concrete();Parallel3DMaterial wrapped(2,{&c},{1.});PlateFiberMaterial p(3,wrapped);
    double thickness[3]={.03,.04,.03};NDMaterial* materials[3]={&p,&p,&p};
    LayeredShellFiberSection section(4,3,thickness,materials);
    Domain domain;
    domain.addNode(new Node(1,6,0.,0.,0.));domain.addNode(new Node(2,6,1.,0.,0.));
    domain.addNode(new Node(3,6,1.,1.,0.));domain.addNode(new Node(4,6,0.,1.,0.));
    auto shell=new ShellMITC4(1,1,2,3,4,section);domain.addElement(shell);
    require(shell->update()==0,"shell zero trial failed");
    require(domain.commit()==0,"valid domain commit failed");
    Vector bad(6);bad(0)=std::numeric_limits<double>::quiet_NaN();domain.getNode(2)->setTrialDisp(bad);
    require(shell->update()<0,"ShellMITC4 swallowed material failure return");
    require(domain.update(1.,1.)<0,"timed Domain::update swallowed material failure return");
    require(domain.commit()<0,"Domain committed a rejected shell trial");
    require(domain.revertToLastCommit()==0,"domain revert failed");
    require(domain.getNode(2)->getDisp().Norm()==0.,"rejected domain trial polluted committed nodes");
    require(domain.getCurrentTime()==0.,"rejected domain trial advanced committed time");
}
int main(int argc,char** argv) {
    Py_Initialize();
    try {
        if(argc>1 && std::string(argv[1])=="state")state_test();
        else if(argc>1 && std::string(argv[1])=="shell")shell_failure_test();
        else if(argc>1 && std::string(argv[1])=="root")root_test();
        else if(argc>1 && std::string(argv[1])=="root-scan")root_test(true);
        else if(argc>1 && std::string(argv[1])=="bracket")bracket_test();
        else if(argc>1 && std::string(argv[1])=="overflow")overflow_test();
        else if(argc>1 && std::string(argv[1])=="no-root")no_root_test();
        else if(argc>1 && std::string(argv[1])=="serialization")serialization_test();
        else { state_test();root_test();shell_failure_test();bracket_test();overflow_test();no_root_test();serialization_test(); }
        std::cout<<"native material regression passed\n";return 0;
    } catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<"\n";return 1; }
}
